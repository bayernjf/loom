"""Q161 客户效果批量回填异步导入任务（镜像 Q137 export_jobs 的写侧）。

与导出共享同一套任务/流/worker 纪律，差别有两点：
1. 导入是写、必须能在后台重放，故输入 payload（CSV 原文或 Excel .xlsx base64）
   原样落 import_jobs.payload；导出不存 payload、下载时按参数重查渲染。
2. 业务校验失败（CsvValidationError / EffectValidationError）是确定性的——重试
   结果不变，process_import_job 直接把任务置 failed（存截断的逐行 errors）并正常
   返回，由 worker ACK，不进 PEL 重试、不进死信；只有基础设施异常（DB/Redis）才
   抛出，留 PEL 由 XCLAIM 接管、超 MAX_DELIVERIES 进死信。

门控 LOOM_IMPORT_WORKER_ENABLED 默认 false：关闭时 POST /jobs 先提交 queued 任务
随即在请求内同步执行到终态（completed/failed），保持 V1 单副本行为；开启时只建
queued 并 XADD 到导入流，ImportWorker 异步置 running→completed/failed。
"""

import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.audit import append_audit
from app.core.config import get_settings
from app.core.effects.csv_io import CsvValidationError
from app.core.effects.schemas import (
    CustomerBackfillExcelUploadIn,
    CustomerBackfillUploadIn,
)
from app.core.effects.service import (
    EffectValidationError,
    ingest_customer_backfill_excel,
    ingest_customer_backfill_upload,
)
from app.core.imports.models import (
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_TERMINAL_STATES,
    ImportJob,
)
from app.core.imports.schemas import BackfillImportJobIn
from app.core.metrics.business import record_job_failed
from app.core.queue import (
    DEFAULT_MAXLEN,
    add_event,
    ensure_group,
)
from app.core.queue import streams as streams_mod

logger = logging.getLogger(__name__)

IMPORT_STREAM = "loom:stream:imports"
IMPORT_GROUP = "import-workers"
IMPORT_DEAD_STREAM = "loom:stream:imports:dead"

# 后台 worker 的系统 Actor（roles=[]，不经 HTTP/RBAC，同 Q137 内部入口口径）。
WORKER_ACTOR = "system:import-worker"

# 失败任务只持久化前 N 条逐行错误，避免畸形大文件撑爆 errors Text。
MAX_STORED_ERRORS = 100


async def enqueue_import_job(job_id: str) -> None:
    """queued 任务提交后 XADD 到导入流（消费组 mkstream 幂等建组）。

    Redis 故障抛 StreamBackendError（fail-closed）：调用方据此把任务置 failed，
    绝不留一条永远无人消费的 queued 任务。
    """

    client = streams_mod._get_client()
    await ensure_group(client, IMPORT_STREAM, IMPORT_GROUP)
    await add_event(client, IMPORT_STREAM, {"job_id": job_id}, maxlen=DEFAULT_MAXLEN)


def _payload_of(body: BackfillImportJobIn) -> str:
    return body.csv if body.format == "csv" else (body.content_base64 or "")


async def create_queued_import_job(
    session: AsyncSession, body: BackfillImportJobIn
) -> ImportJob:
    """建 queued 导入任务并固化可重放 payload（不解析、不执行），由调用方提交后入流。"""

    job = ImportJob(
        job_id=str(uuid.uuid4()),
        tenant_id=body.tenant_id,
        content_id=body.content_id,
        format=body.format,
        payload=_payload_of(body),
        filename=body.filename,
        status=JOB_QUEUED,
        requested_by=body.actor.id,
    )
    session.add(job)
    await session.flush()
    await append_audit(
        session,
        tenant_id=body.tenant_id,
        actor_id=body.actor.id,
        actor_roles=[],
        action="import.job_created",
        entity_type="import_job",
        entity_id=job.job_id,
        detail={
            "format": body.format,
            "content_id": body.content_id,
            "filename": body.filename,
        },
    )
    return job


def _stored_errors(errors: list[dict]) -> str:
    return json.dumps(errors[:MAX_STORED_ERRORS], ensure_ascii=False)


async def process_import_job(
    session: AsyncSession, job: ImportJob
) -> ImportJob:
    """worker / 同步路径：置 running → 解析回填 → completed/failed。

    确定性业务校验失败内聚为 failed（不抛出，调用方照常提交并 ACK）；基础设施
    异常向上抛（worker 留 PEL 接管重试）。返回的 job 实例在业务失败分支为重新
    读取的持久化行（rollback 清掉 ingest 脏对象后原实例已过期）。
    """

    # 先把任务标量字段读到局部变量：业务失败分支会 rollback（expire 掉 job
    # 实例），rollback 后再访问 job.job_id 等会触发同步懒加载（MissingGreenlet）。
    job_id = job.job_id
    tenant_id = job.tenant_id
    content_id = job.content_id
    payload = job.payload
    filename = job.filename

    job.status = JOB_RUNNING
    job.error = None
    await session.flush()

    max_rows = get_settings().backfill_upload_max_rows
    actor = Actor(id=job.requested_by, roles=[])
    try:
        if job.format == "csv":
            receipt = await ingest_customer_backfill_upload(
                session,
                body=CustomerBackfillUploadIn(
                    tenant_id=tenant_id,
                    content_id=content_id,
                    csv=payload,
                    filename=filename,
                    actor=actor,
                ),
                max_rows=max_rows,
            )
        else:
            receipt = await ingest_customer_backfill_excel(
                session,
                body=CustomerBackfillExcelUploadIn(
                    tenant_id=tenant_id,
                    content_id=content_id,
                    content_base64=payload,
                    filename=filename,
                    actor=actor,
                ),
                max_rows=max_rows,
            )
    except CsvValidationError as exc:
        # 确定性载体/逐行校验失败：回滚未提交的写入，落 failed（不重试、不进死信）。
        await session.rollback()
        failed = await session.get(ImportJob, job_id)
        failed.status = JOB_FAILED
        # Q188：确定性校验失败（不重试、不进死信）同样是作业失败。
        record_job_failed("import")
        failed.error = str(exc)
        failed.errors = _stored_errors(exc.errors)
        failed.completed_at = datetime.now(UTC)
        await append_audit(
            session,
            tenant_id=failed.tenant_id,
            actor_id=WORKER_ACTOR,
            actor_roles=[],
            action="import.job_failed",
            entity_type="import_job",
            entity_id=failed.job_id,
            detail={"reason": "validation", "errors": len(exc.errors)},
        )
        return failed
    except EffectValidationError as exc:
        await session.rollback()
        failed = await session.get(ImportJob, job_id)
        errors = [{"index": exc.index, "field": exc.field, "message": str(exc)}]
        failed.status = JOB_FAILED
        # Q188：效果校验的确定性失败同样是作业终态失败，与入流/死信路径同计数。
        record_job_failed("import")
        failed.error = str(exc)
        failed.errors = _stored_errors(errors)
        failed.completed_at = datetime.now(UTC)
        await append_audit(
            session,
            tenant_id=failed.tenant_id,
            actor_id=WORKER_ACTOR,
            actor_roles=[],
            action="import.job_failed",
            entity_type="import_job",
            entity_id=failed.job_id,
            detail={"reason": "effect_validation"},
        )
        return failed

    job.received = receipt["received"]
    job.matched = receipt["matched"]
    job.orphan = receipt["orphan"]
    job.upserted = receipt["upserted"]
    job.row_count = len(receipt["rows"])
    job.status = JOB_COMPLETED
    job.error = None
    job.errors = None
    job.completed_at = datetime.now(UTC)
    await append_audit(
        session,
        tenant_id=job.tenant_id,
        actor_id=WORKER_ACTOR,
        actor_roles=[],
        action="import.job_completed",
        entity_type="import_job",
        entity_id=job.job_id,
        detail={
            "received": receipt["received"],
            "matched": receipt["matched"],
            "upserted": receipt["upserted"],
        },
    )
    return job


async def fail_import_job(
    session: AsyncSession, job: ImportJob, error: str
) -> ImportJob:
    """入流失败 / 死信：置 failed，留痕可查（镜像 export fail_export_job）。"""

    job.status = JOB_FAILED
    # Q188：入流 fail-closed 的 router 也走本函数，请求路径同样被计入。
    record_job_failed("import")
    job.error = error[:2000]
    job.completed_at = datetime.now(UTC)
    await append_audit(
        session,
        tenant_id=job.tenant_id,
        actor_id=WORKER_ACTOR,
        actor_roles=[],
        action="import.job_failed",
        entity_type="import_job",
        entity_id=job.job_id,
        detail={"error": error[:500]},
    )
    return job


def is_terminal(job: ImportJob) -> bool:
    return job.status in JOB_TERMINAL_STATES


def _parsed_errors(raw: str | None) -> list[dict] | None:
    if not raw:
        return None
    try:
        loaded = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(loaded, list):
        return None
    return [item for item in loaded if isinstance(item, dict)]


def job_view(job: ImportJob) -> dict:
    return {
        "job_id": job.job_id,
        "tenant_id": job.tenant_id,
        "content_id": job.content_id,
        "format": job.format,
        "filename": job.filename,
        "status": job.status,
        "received": job.received,
        "matched": job.matched,
        "orphan": job.orphan,
        "upserted": job.upserted,
        "row_count": job.row_count,
        "requested_by": job.requested_by,
        "error": job.error,
        "errors": _parsed_errors(job.errors),
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


async def list_jobs(
    session: AsyncSession,
    *,
    tenant_id: str,
    content_id: str | None = None,
    limit: int = 50,
) -> list[ImportJob]:
    """任务列表口：按租户倒序（可选成品过滤），不含 payload 大字段。"""

    stmt = select(ImportJob).where(ImportJob.tenant_id == tenant_id)
    if content_id:
        stmt = stmt.where(ImportJob.content_id == content_id)
    stmt = stmt.order_by(ImportJob.created_at.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


async def get_job(session: AsyncSession, job_id: str) -> ImportJob | None:
    return await session.get(ImportJob, job_id)


async def get_scoped_job(
    session: AsyncSession, job_id: str, tenant_id: str
) -> ImportJob | None:
    return await session.scalar(
        select(ImportJob).where(
            ImportJob.job_id == job_id,
            ImportJob.tenant_id == tenant_id,
        )
    )
