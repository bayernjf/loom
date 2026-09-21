"""Q161 客户效果批量回填异步导入任务端点。

路径挂在效果回填命名空间下（/api/effects/backfill/jobs），与 Q156/Q160 同步上传
端点同一业务契约，区别仅在于这是「可轮询的任务」形态：
- worker 门控关（V1 默认）：POST 先提交 queued 任务，随即请求内同步执行到终态，
  201 直接回 completed/failed 的任务视图（确定性校验失败的逐行错误在 errors）；
- worker 门控开（多副本）：POST 回 queued，由 ImportWorker 异步处理，GET 轮询；
  入流基础设施失败 fail-closed 置 failed 并回 503。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.imports import service
from app.core.imports.schemas import (
    BackfillImportJobIn,
    BackfillImportJobList,
    BackfillImportJobView,
)
from app.core.queue import StreamBackendError

router = APIRouter(prefix="/api/effects/backfill", tags=["effects-backfill-imports"])


@router.post("/jobs", response_model=BackfillImportJobView, status_code=201)
async def create_backfill_import_job(
    body: BackfillImportJobIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """创建批量回填导入任务（CSV 原文或 Excel .xlsx base64）。"""

    job = await service.create_queued_import_job(session, body)
    # 先提交 queued（worker 读到时任务与 payload 必须已可见）。
    await session.commit()

    if not get_settings().import_worker_enabled:
        # V1 默认：请求内同步执行到终态（completed/failed），再提交一次。
        running = await service.get_job(session, job.job_id)
        running = await service.process_import_job(session, running)
        await session.commit()
        return service.job_view(running)

    try:
        await service.enqueue_import_job(job.job_id)
    except StreamBackendError:
        # 入流失败 fail-closed：置 failed，绝不留无人消费的 queued 任务。
        stale = await service.get_job(session, job.job_id)
        await service.fail_import_job(
            session, stale, "enqueue failed: stream backend unavailable"
        )
        await session.commit()
        raise HTTPException(
            status_code=503, detail="import queue unavailable; job marked failed"
        ) from None
    return service.job_view(job)


@router.get("/jobs", response_model=BackfillImportJobList)
async def list_backfill_import_jobs(
    tenant_id: str = Query(min_length=1),
    content_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """任务列表口：按租户倒序（可选成品过滤），不含 payload 大字段。"""

    jobs = await service.list_jobs(
        session, tenant_id=tenant_id, content_id=content_id, limit=limit
    )
    return {
        "tenant_id": tenant_id,
        "count": len(jobs),
        "jobs": [service.job_view(job) for job in jobs],
    }


@router.get("/jobs/{job_id}", response_model=BackfillImportJobView)
async def get_backfill_import_job(
    job_id: str,
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """任务状态查询（租户隔离；供轮询 queued/running/completed/failed）。"""

    job = await service.get_scoped_job(session, job_id, tenant_id)
    if job is None:
        raise HTTPException(status_code=404, detail="import job not found")
    return service.job_view(job)
