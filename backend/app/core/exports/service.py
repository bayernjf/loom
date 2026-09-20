"""M12 中台导出（Q100/Q132）：FCW final_id 单列 CSV、JSON 形态与导出任务。

契约（docs/05 D4，02 C1.44 拍板；Q132/C1.76 扩 JSON 与任务记录）：中台手动
用，M12 验收口径“CSV 只消费 final_id”——仅导一列 final_id（含表头），不
拼装 6 层原料包。读路径同 Q98/Q99：不触发 Q95 准入门，未知租户返回空结果
（CSV 仅表头、JSON 空 envelope）200；只导 published（draft 不导出；Q32
revoked 急停操作 V1 尚未落地，其态一旦实现亦自然被 published 过滤排除——
前向兼容）。

Q132：JSON 形态与 CSV 同口径；导出任务（export_jobs）V1 在请求内同步执行
并置 completed，下载按任务参数重新查询渲染（不存文件大字段、幂等反映当前
published 集合），queued/running 后台 worker 随 V2（Redis Streams）。
"""

import csv
import io
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.exports.models import (
    EXPORT_FORMATS,
    FORMAT_JSON,
    JOB_COMPLETED,
    ExportJob,
)
from app.final.final_whitelist.models import (
    PUBLISH_PUBLISHED,
    FinalContentWhitelist,
)

CSV_HEADER = ("final_id",)


async def exported_final_ids(
    session: AsyncSession,
    *,
    tenant_id: str,
    product_space_id: str | None = None,
) -> list[str]:
    stmt = (
        select(FinalContentWhitelist.final_id)
        .where(
            FinalContentWhitelist.tenant_id == tenant_id,
            FinalContentWhitelist.publish_status == PUBLISH_PUBLISHED,
        )
        .order_by(FinalContentWhitelist.created_at.desc())
    )
    if product_space_id:
        stmt = stmt.where(
            FinalContentWhitelist.product_space_id == product_space_id
        )
    rows = await session.scalars(stmt)
    return list(rows.all())


def render_csv(final_ids: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    writer.writerows((final_id,) for final_id in final_ids)
    return buffer.getvalue()


def render_json(
    tenant_id: str, product_space_id: str | None, final_ids: list[str]
) -> dict:
    """Q132 JSON 形态：与 CSV 同口径（只 final_id），envelope 便于中台核对。"""

    return {
        "tenant_id": tenant_id,
        "product_space_id": product_space_id,
        "count": len(final_ids),
        "final_ids": final_ids,
    }


def file_name_for(tenant_id: str, fmt: str) -> str:
    return f"fcw-{tenant_id}.{fmt}"


def render_payload(
    tenant_id: str,
    product_space_id: str | None,
    fmt: str,
    final_ids: list[str],
) -> tuple[str, str]:
    """按格式渲染下载体，返回 (media_type, body)。"""

    if fmt == FORMAT_JSON:
        body = json.dumps(
            render_json(tenant_id, product_space_id, final_ids),
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
    final_ids = await exported_final_ids(
        session, tenant_id=tenant_id, product_space_id=product_space_id
    )
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
        },
    )
    return job


async def get_job(session: AsyncSession, job_id: str) -> ExportJob | None:
    return await session.get(ExportJob, job_id)


async def render_job(
    session: AsyncSession, job: ExportJob
) -> tuple[str, str]:
    """下载时按任务参数重新查询渲染（幂等，反映当前 published 集合）。"""

    final_ids = await exported_final_ids(
        session,
        tenant_id=job.tenant_id,
        product_space_id=job.product_space_id,
    )
    return render_payload(
        job.tenant_id, job.product_space_id, job.format, final_ids
    )
