"""M12 中台导出端点（Q100 CSV / Q132 JSON + 导出任务）。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.exports import service
from app.core.exports.models import JOB_FAILED
from app.core.exports.schemas import ExportJobCreate, ExportJobView

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
    """Q132：创建导出任务（V1 同步执行并置 completed，后台 worker 随 V2）。"""

    job = await service.create_export_job(
        session,
        tenant_id=body.tenant_id,
        product_space_id=body.product_space_id,
        fmt=body.format,
        actor_id=body.actor.id,
    )
    await session.commit()
    return service.job_view(job)


@router.get("/jobs/{job_id}", response_model=ExportJobView)
async def get_export_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """导出任务状态查询（V2 真异步后供中台轮询；V1 创建即 completed）。"""

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
    media_type, body = await service.render_job(session, job)
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{job.file_name}"'
        },
    )
