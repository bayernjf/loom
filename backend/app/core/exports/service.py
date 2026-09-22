"""M12 中台导出（Q100/Q132）：FCW final_id 单列 CSV、JSON 形态与导出任务。

契约（docs/05 D4，02 C1.44 拍板；Q132/C1.76 扩 JSON 与任务记录）：中台手动
用，M12 验收口径“CSV 只消费 final_id”——仅导一列 final_id（含表头），不
拼装 6 层原料包。读路径同 Q98/Q99：不触发 Q95 准入门，未知租户返回空结果
（CSV 仅表头、JSON 空 envelope）200；只导 published（draft 不导出；Q32
revoked 急停操作 V1 尚未落地，其态一旦实现亦自然被 published 过滤排除——
前向兼容）。

Q132：JSON 形态与 CSV 同口径；导出任务（export_jobs）门控关闭时在请求内同步
执行并置 completed，下载按任务参数重新查询渲染（不存文件大字段、幂等反映当前
published 集合）。

Q137：门控开启（LOOM_EXPORT_WORKER_ENABLED）走真后台 worker——POST 只建
queued 任务并 XADD 到导出流（Redis Streams 消费组 export-workers），进程内
ExportWorker 消费组认领后置 running→completed/failed；崩溃行进 PEL 由 XCLAIM
接管重试，超 MAX_DELIVERIES 进死信流并置 failed。导出只读且下载按参数重渲染，
消费组水平并行天然幂等，无需 leader 锁。
"""

import csv
import io
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.config import get_settings
from app.core.exports.models import (
    EXPORT_FORMATS,
    FORMAT_JSON,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_TERMINAL_STATES,
    ExportJob,
)
from app.core.queue import (
    DEFAULT_MAXLEN,
    add_event,
    ensure_group,
)
from app.core.queue import streams as streams_mod
from app.final.final_whitelist.models import (
    PUBLISH_PUBLISHED,
    FinalContentWhitelist,
)

logger = logging.getLogger(__name__)

CSV_HEADER = ("final_id",)

# Q137 导出任务流 / 消费组 / 超限死信流（与 restock 流隔离，复用 queue 通用原语）。
EXPORT_STREAM = "loom:stream:exports"
EXPORT_GROUP = "export-workers"
EXPORT_DEAD_STREAM = "loom:stream:exports:dead"

# 后台 worker 的系统 Actor（roles=[]，不经 HTTP/RBAC，同 Q87 内部入口口径）。
WORKER_ACTOR = "system:export-worker"


def _published_stmt(tenant_id: str, product_space_id: str | None, column):
    stmt = select(column).where(
        FinalContentWhitelist.tenant_id == tenant_id,
        FinalContentWhitelist.publish_status == PUBLISH_PUBLISHED,
    )
    if product_space_id:
        stmt = stmt.where(
            FinalContentWhitelist.product_space_id == product_space_id
        )
    return stmt


async def exported_final_ids(
    session: AsyncSession,
    *,
    tenant_id: str,
    product_space_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[str]:
    """Q142：支持 limit/offset 分页（created_at DESC）。

    limit 为 None 时不加 LIMIT 子句；调用方负责在需要体量治理时传入硬上限
    （见 ``fetch_export_page``）。
    """

    stmt = _published_stmt(
        tenant_id, product_space_id, FinalContentWhitelist.final_id
    ).order_by(FinalContentWhitelist.created_at.desc())
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = await session.scalars(stmt)
    return list(rows.all())


async def count_exported_final_ids(
    session: AsyncSession,
    *,
    tenant_id: str,
    product_space_id: str | None = None,
) -> int:
    """Q142：匹配过滤条件的 published 总数（分页 total，不受 limit/offset 影响）。"""

    stmt = _published_stmt(
        tenant_id, product_space_id, func.count(FinalContentWhitelist.final_id)
    )
    return int(await session.scalar(stmt))


async def fetch_export_page(
    session: AsyncSession,
    *,
    tenant_id: str,
    product_space_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> dict:
    """Q142：统一取一页导出数据 + 分页元数据。

    - 显式 ``limit`` 为页大小（路由层已保证 <= ``export_max_rows``）；
    - ``limit=None`` 时回落到 settings.export_max_rows 硬上限（体量治理）；
    - 返回 final_ids/total/limit/offset/has_more/truncated。``truncated`` 表示
      未显式分页但结果被硬上限截断（offset=0 且仍有更多）。
    """

    max_rows = get_settings().export_max_rows
    explicit = limit is not None
    effective_limit = limit if explicit else max_rows
    total = await count_exported_final_ids(
        session, tenant_id=tenant_id, product_space_id=product_space_id
    )
    final_ids = await exported_final_ids(
        session,
        tenant_id=tenant_id,
        product_space_id=product_space_id,
        limit=effective_limit,
        offset=offset,
    )
    has_more = offset + len(final_ids) < total
    return {
        "final_ids": final_ids,
        "total": total,
        "limit": effective_limit,
        "offset": offset,
        "has_more": has_more,
        # 未显式分页（全量导出/任务路径）却仍有更多行，即被硬上限截断。
        "truncated": has_more and not explicit and offset == 0,
    }


def render_csv(final_ids: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    writer.writerows((final_id,) for final_id in final_ids)
    return buffer.getvalue()


def render_json(
    tenant_id: str,
    product_space_id: str | None,
    final_ids: list[str],
    *,
    total: int | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> dict:
    """Q132 JSON 形态：与 CSV 同口径（只 final_id），envelope 便于中台核对。

    Q142：追加分页元数据 ``total``（匹配条件总数）/``limit``/``offset``/
    ``has_more``；``count`` 仍为本页实际行数。未提供分页信息（纯函数直接调用）
    时按"本页即全部"退化，has_more 恒 False，保持向后兼容。
    """

    page_total = len(final_ids) if total is None else total
    page_limit = len(final_ids) if limit is None else limit
    has_more = offset + len(final_ids) < page_total
    return {
        "tenant_id": tenant_id,
        "product_space_id": product_space_id,
        "count": len(final_ids),
        "total": page_total,
        "limit": page_limit,
        "offset": offset,
        "has_more": has_more,
        "final_ids": final_ids,
    }


def file_name_for(tenant_id: str, fmt: str) -> str:
    return f"fcw-{tenant_id}.{fmt}"


def render_payload(
    tenant_id: str,
    product_space_id: str | None,
    fmt: str,
    final_ids: list[str],
    *,
    page: dict | None = None,
) -> tuple[str, str]:
    """按格式渲染下载体，返回 (media_type, body)。

    Q142：``page`` 携带 total/limit/offset 供 JSON envelope 输出分页元数据；
    CSV 严格单列正文不变（分页信息走响应头，见路由层）。
    """

    if fmt == FORMAT_JSON:
        kwargs = {}
        if page is not None:
            kwargs = {
                "total": page["total"],
                "limit": page["limit"],
                "offset": page["offset"],
            }
        body = json.dumps(
            render_json(tenant_id, product_space_id, final_ids, **kwargs),
            ensure_ascii=False,
            indent=2,
        )
        return "application/json; charset=utf-8", body + "\n"
    return "text/csv; charset=utf-8", render_csv(final_ids)


def job_view(job: ExportJob) -> dict:
    return {
        "job_id": job.job_id,
        "tenant_id": job.tenant_id,
        "product_space_id": job.product_space_id,
        "format": job.format,
        "status": job.status,
        "row_count": job.row_count,
        "file_name": job.file_name,
        "requested_by": job.requested_by,
        "error": job.error,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "download_url": f"/api/exports/jobs/{job.job_id}/download",
    }


async def create_export_job(
    session: AsyncSession,
    *,
    tenant_id: str,
    product_space_id: str | None,
    fmt: str,
    actor_id: str,
) -> ExportJob:
    """Q132：同步执行导出并落任务记录（V1 创建即 completed）。"""

    if fmt not in EXPORT_FORMATS:
        # 路由层 pydantic Literal 已挡，此闸为服务层防御。
        raise ValueError(f"unsupported export format: {fmt}")
    # Q142：任务路径不接受分页参数，受 export_max_rows 硬上限保护（截断留痕）。
    page = await fetch_export_page(
        session, tenant_id=tenant_id, product_space_id=product_space_id
    )
    final_ids = page["final_ids"]
    job = ExportJob(
        job_id=str(uuid.uuid1()),
        tenant_id=tenant_id,
        product_space_id=product_space_id,
        format=fmt,
        status=JOB_COMPLETED,
        row_count=len(final_ids),
        file_name=file_name_for(tenant_id, fmt),
        requested_by=actor_id,
        completed_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_roles=[],
        action="export.job_created",
        entity_type="export_job",
        entity_id=job.job_id,
        detail={
            "format": fmt,
            "row_count": len(final_ids),
            "product_space_id": product_space_id,
            "total": page["total"],
            "limit": page["limit"],
            "truncated": page["truncated"],
        },
    )
    return job


async def create_queued_export_job(
    session: AsyncSession,
    *,
    tenant_id: str,
    product_space_id: str | None,
    fmt: str,
    actor_id: str,
) -> ExportJob:
    """Q137：建 queued 任务（不渲染、row_count=0），由 POST 提交后 XADD 入流。"""

    if fmt not in EXPORT_FORMATS:
        # 路由层 pydantic Literal 已挡，此闸为服务层防御。
        raise ValueError(f"unsupported export format: {fmt}")
    job = ExportJob(
        job_id=str(uuid.uuid1()),
        tenant_id=tenant_id,
        product_space_id=product_space_id,
        format=fmt,
        status=JOB_QUEUED,
        row_count=0,
        file_name=file_name_for(tenant_id, fmt),
        requested_by=actor_id,
    )
    session.add(job)
    await session.flush()
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_roles=[],
        action="export.job_created",
        entity_type="export_job",
        entity_id=job.job_id,
        detail={
            "format": fmt,
            "product_space_id": product_space_id,
            "mode": "async",
        },
    )
    return job


async def enqueue_export_job(job_id: str) -> None:
    """Q137：queued 任务提交后 XADD 到导出流（消费组 mkstream 幂等建组）。

    Redis 故障抛 StreamBackendError（fail-closed）：调用方据此把任务置 failed，
    绝不留一条永远无人消费的 queued 任务。
    """

    client = streams_mod._get_client()
    await ensure_group(client, EXPORT_STREAM, EXPORT_GROUP)
    await add_event(
        client,
        EXPORT_STREAM,
        {"job_id": job_id},
        maxlen=DEFAULT_MAXLEN,
    )


async def process_export_job(
    session: AsyncSession, job: ExportJob
) -> ExportJob:
    """Q137 worker：置 running → 重查渲染计数 → completed（幂等，反映当前集合）。"""

    job.status = JOB_RUNNING
    job.error = None
    await session.flush()
    # Q142：worker 渲染同样受 export_max_rows 硬上限保护（截断留痕）。
    page = await fetch_export_page(
        session,
        tenant_id=job.tenant_id,
        product_space_id=job.product_space_id,
    )
    final_ids = page["final_ids"]
    job.row_count = len(final_ids)
    job.status = JOB_COMPLETED
    job.completed_at = datetime.now(UTC)
    await append_audit(
        session,
        tenant_id=job.tenant_id,
        actor_id=WORKER_ACTOR,
        actor_roles=[],
        action="export.job_completed",
        entity_type="export_job",
        entity_id=job.job_id,
        detail={
            "row_count": len(final_ids),
            "total": page["total"],
            "truncated": page["truncated"],
        },
    )
    return job


async def fail_export_job(
    session: AsyncSession, job: ExportJob, error: str
) -> ExportJob:
    """Q137 worker：置 failed（超限死信/渲染持续失败），留痕可查。"""

    job.status = JOB_FAILED
    job.error = error[:2000]
    job.completed_at = datetime.now(UTC)
    await append_audit(
        session,
        tenant_id=job.tenant_id,
        actor_id=WORKER_ACTOR,
        actor_roles=[],
        action="export.job_failed",
        entity_type="export_job",
        entity_id=job.job_id,
        detail={"error": error[:500]},
    )
    return job


def is_terminal(job: ExportJob) -> bool:
    return job.status in JOB_TERMINAL_STATES


async def list_jobs(
    session: AsyncSession,
    *,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[ExportJob]:
    """Q137 任务列表口：按租户倒序返回（中台轮询/核对），不含文件体。"""

    stmt = (
        select(ExportJob)
        .where(ExportJob.tenant_id == tenant_id)
        .order_by(ExportJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(stmt)).all())


async def get_job(session: AsyncSession, job_id: str) -> ExportJob | None:
    return await session.get(ExportJob, job_id)


async def render_job(
    session: AsyncSession, job: ExportJob
) -> tuple[str, str, dict]:
    """下载时按任务参数重新查询渲染（幂等，反映当前 published 集合）。

    Q142：返回 (media_type, body, page)，page 携带硬上限下的分页元数据
    （JSON 入 envelope；CSV 由路由层写 X-* 响应头）。
    """

    page = await fetch_export_page(
        session,
        tenant_id=job.tenant_id,
        product_space_id=job.product_space_id,
    )
    media_type, body = render_payload(
        job.tenant_id,
        job.product_space_id,
        job.format,
        page["final_ids"],
        page=page,
    )
    return media_type, body, page
