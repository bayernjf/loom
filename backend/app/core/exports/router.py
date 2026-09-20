"""M12 中台导出端点（Q100 CSV / Q132 JSON + 导出任务 / Q137 真后台 worker）。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.exports import service
from app.core.exports.models import JOB_COMPLETED, JOB_FAILED
from app.core.exports.schemas import ExportJobCreate, ExportJobView
from app.core.queue import StreamBackendError

router = APIRouter(prefix="/api/exports", tags=["middleground-export"])


@router.get("/fcw.csv")
async def export_fcw_csv(
    tenant_id: str = Query(min_length=1),
    product_space_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> Response:
    # Q100：中台手动拉取白名单 final_id 单列。读路径不触发 Q95 准入门
    # （未知租户=仅表头空文件 200）；只导 published（draft 排除，Q32
    # revoked 落地后同过滤自然生效）。
    final_ids = await service.exported_final_ids(
        session, tenant_id=tenant_id, product_space_id=product_space_id
    )
    body = service.render_csv(final_ids)
    filename = f"fcw-{tenant_id}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/fcw.json")
async def export_fcw_json(
    tenant_id: str = Query(min_length=1),
    product_space_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    # Q132：JSON 形态与 CSV 同口径（只 final_id、只 published、未知租户空 200）。
    final_ids = await service.exported_final_ids(
        session, tenant_id=tenant_id, product_space_id=product_space_id
    )
    payload = service.render_json(tenant_id, product_space_id, final_ids)
    filename = f"fcw-{tenant_id}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/jobs", response_model=ExportJobView, status_code=201)
async def create_export_job(
    body: ExportJobCreate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """创建导出任务。

    Q132：门控关闭时请求内同步执行并置 completed；Q137：门控开启时建 queued
    任务并 XADD 入导出流，由 ExportWorker 异步置 running→completed，中台经
    状态口/列表口轮询。
    """

    if not get_settings().export_worker_enabled:
        job = await service.create_export_job(
            session,
            tenant_id=body.tenant_id,
            product_space_id=body.product_space_id,
            fmt=body.format,
            actor_id=body.actor.id,
        )
        await session.commit()
        return service.job_view(job)

    job = await service.create_queued_export_job(
        session,
        tenant_id=body.tenant_id,
        product_space_id=body.product_space_id,
        fmt=body.format,
        actor_id=body.actor.id,
    )
    # 先提交 queued（worker 读到时任务必须已可见），再入流。
    await session.commit()
    try:
        await service.enqueue_export_job(job.job_id)
    except StreamBackendError:
        # 入流失败 fail-closed：置 failed，绝不留一条无人消费的 queued 任务。
        await service.fail_export_job(
            session, job, "enqueue failed: stream backend unavailable"
        )
        await session.commit()
        raise HTTPException(
            status_code=503, detail="export queue unavailable; job marked failed"
        ) from None
    return service.job_view(job)


@router.get("/jobs")
async def list_export_jobs(
    tenant_id: str = Query(min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Q137 任务列表口：按租户倒序（中台轮询/核对），不含文件体。"""

    jobs = await service.list_jobs(session, tenant_id=tenant_id, limit=limit)
    return {
        "tenant_id": tenant_id,
        "count": len(jobs),
        "jobs": [service.job_view(job) for job in jobs],
    }


@router.get("/jobs/{job_id}", response_model=ExportJobView)
async def get_export_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """导出任务状态查询（Q137 异步后供中台轮询 queued/running/completed）。"""

    job = await service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="export job not found")
    return service.job_view(job)


@router.get("/jobs/{job_id}/download")
async def download_export_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """按任务参数重新查询渲染下载（幂等，反映当前 published 集合，不存 payload）。"""

    job = await service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="export job not found")
    if job.status == JOB_FAILED:
        raise HTTPException(status_code=409, detail=job.error or "export job failed")
    if job.status != JOB_COMPLETED:
        # Q137：queued/running 尚未就绪，中台应轮询状态口后再下载。
        raise HTTPException(
            status_code=409, detail=f"export job not ready (status={job.status})"
        )
    media_type, body = await service.render_job(session, job)
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{job.file_name}"'
        },
    )
