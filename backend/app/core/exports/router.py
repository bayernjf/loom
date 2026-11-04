"""M12 中台导出端点（Q100 CSV / Q132 JSON + 导出任务 / Q137 真后台 worker）。

P1-1（2026-11-02 评审）：六口全部由「零凭证 + 可猜测 tenant_id」收口为
Agent Key 机器凭证（fcw.csv/json 本就是系统间分发的白名单面；jobs 族由前端
服务端以 env 持有的 Key 调用）。缺失/错误/吊销统一 401。
"""

import re
from typing import Any, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_keys.models import AgentApiKey
from app.core.api_keys.service import require_agent_key
from app.core.config import get_settings
from app.core.db import get_session
from app.core.exports import service
from app.core.exports.models import JOB_COMPLETED, JOB_FAILED
from app.core.exports.schemas import ExportJobCreate, ExportJobView
from app.core.queue import StreamBackendError

router = APIRouter(prefix="/api/exports", tags=["middleground-export"])


async def require_export_key(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> AgentApiKey:
    """导出面 Bearer Agent Key 验签（Q88 依赖需要位置参 session，与 Q150 同法包一层）。"""

    return await require_agent_key(session, authorization)


# 接线自检标记：路由上的 Depends 被删掉时，结构用例据此判红。
cast(Any, require_export_key).loom_requires_agent_credential = True


def _validate_page(limit: int | None, offset: int) -> None:
    # Q142：页大小不得超过硬上限；不传 limit 时由 service 回落到硬上限。
    max_rows = get_settings().export_max_rows
    if limit is not None and limit > max_rows:
        raise HTTPException(
            status_code=422,
            detail=f"limit must be <= {max_rows} (export_max_rows)",
        )


def _content_disposition(filename: str) -> str:
    """P2-4：文件名来自调用方可影响的值（fcw-<tenant_id>.* / job.file_name）。

    tenant_id 能含 CR/LF、引号或分隔符，直接拼进 Content-Disposition 就是响应头
    注入。ASCII fallback 只留 [A-Za-z0-9._-]，其余替换为 `_`；原始值走 RFC 5987
    ``filename*``（percent-encoded UTF-8），中文租户名仍可辨识且头值无控制字符。
    """

    raw = filename.replace("\r", "").replace("\n", "")
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._") or "export"
    encoded = quote(raw, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def _page_headers(page: dict, filename: str) -> dict:
    # Q142：CSV 正文严格单列，分页/截断信息走 X-* 响应头。
    return {
        "Content-Disposition": _content_disposition(filename),
        "X-Export-Total": str(page["total"]),
        "X-Export-Limit": str(page["limit"]),
        "X-Export-Offset": str(page["offset"]),
        "X-Export-Has-More": "true" if page["has_more"] else "false",
        "X-Export-Truncated": "true" if page["truncated"] else "false",
    }


@router.get("/fcw.csv")
async def export_fcw_csv(
    tenant_id: str = Query(min_length=1),
    product_space_id: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: AgentApiKey = Depends(require_export_key),
) -> Response:
    # Q100：中台手动拉取白名单 final_id 单列。读路径不触发 Q95 准入门
    # （未知租户=仅表头空文件 200）；只导 published（draft 排除，Q32
    # revoked 落地后同过滤自然生效）。Q142：支持 limit/offset 分页与硬上限。
    _validate_page(limit, offset)
    page = await service.fetch_export_page(
        session,
        tenant_id=tenant_id,
        product_space_id=product_space_id,
        limit=limit,
        offset=offset,
    )
    body = service.render_csv(page["final_ids"])
    filename = f"fcw-{tenant_id}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers=_page_headers(page, filename),
    )


@router.get("/fcw.json")
async def export_fcw_json(
    tenant_id: str = Query(min_length=1),
    product_space_id: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: AgentApiKey = Depends(require_export_key),
) -> JSONResponse:
    # Q132：JSON 形态与 CSV 同口径（只 final_id、只 published、未知租户空 200）。
    # Q142：envelope 追加 total/limit/offset/has_more 分页元数据。
    _validate_page(limit, offset)
    page = await service.fetch_export_page(
        session,
        tenant_id=tenant_id,
        product_space_id=product_space_id,
        limit=limit,
        offset=offset,
    )
    payload = service.render_json(
        tenant_id,
        product_space_id,
        page["final_ids"],
        total=page["total"],
        limit=page["limit"],
        offset=page["offset"],
    )
    filename = f"fcw-{tenant_id}.json"
    return JSONResponse(
        content=payload,
        headers=_page_headers(page, filename),
    )


@router.post("/jobs", response_model=ExportJobView, status_code=201)
async def create_export_job(
    body: ExportJobCreate,
    session: AsyncSession = Depends(get_session),
    _: AgentApiKey = Depends(require_export_key),
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
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: AgentApiKey = Depends(require_export_key),
) -> dict:
    """Q137 任务列表口：按租户倒序（中台轮询/核对），不含文件体。"""

    jobs = await service.list_jobs(
        session, tenant_id=tenant_id, limit=limit, offset=offset
    )
    return {
        "tenant_id": tenant_id,
        "count": len(jobs),
        "offset": offset,
        "jobs": [service.job_view(job) for job in jobs],
    }


@router.get("/jobs/{job_id}", response_model=ExportJobView)
async def get_export_job(
    job_id: str,
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
    _: AgentApiKey = Depends(require_export_key),
) -> dict:
    """导出任务状态查询（Q137 异步后供中台轮询 queued/running/completed）。

    Q196：``tenant_id`` 必填且任务须属于该租户（同 Q161 导入口口径）——此前只按
    ``job_id`` 直查，任何能打到本口的调用方拿到 id 就能读别的租户的任务。
    """

    job = await service.get_scoped_job(session, job_id, tenant_id)
    if job is None:
        raise HTTPException(status_code=404, detail="export job not found")
    return service.job_view(job)


@router.get("/jobs/{job_id}/download")
async def download_export_job(
    job_id: str,
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
    _: AgentApiKey = Depends(require_export_key),
) -> Response:
    """按任务参数重新查询渲染下载（幂等，反映当前 published 集合，不存 payload）。

    Q196：同状态口，租户必填并按任务行的归属收口。
    """

    job = await service.get_scoped_job(session, job_id, tenant_id)
    if job is None:
        raise HTTPException(status_code=404, detail="export job not found")
    if job.status == JOB_FAILED:
        raise HTTPException(status_code=409, detail=job.error or "export job failed")
    if job.status != JOB_COMPLETED:
        # Q137：queued/running 尚未就绪，中台应轮询状态口后再下载。
        raise HTTPException(
            status_code=409, detail=f"export job not ready (status={job.status})"
        )
    media_type, body, page = await service.render_job(session, job)
    return Response(
        content=body,
        media_type=media_type,
        headers=_page_headers(page, job.file_name),
    )
