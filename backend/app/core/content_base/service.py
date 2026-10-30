"""内容底座持久化服务（M4/T-M4-02）。

状态机与 skill7 候选同构：submit 建 pending_review，review 落
confirmed/modified/rejected。所有写操作 append_audit；不本地兜底产出。
单租户内部自用口径（PRD 明确不做多租户）。
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.content_base import assembly, producers
from app.core.content_base.errors import (
    ContentCandidateNotFound,
    ContentCandidateNotReviewable,
    ContentRequestInvalid,
)
from app.core.content_base.models import ContentCandidateRecord
from app.core.content_base.producers import ContentProducer
from app.core.content_base.types import (
    CandidateStatus,
    ContentCandidate,
    ContentRequest,
    ContentTypeId,
    ReviewDecisionId,
)
from app.core.model_registry import hub

# 内部自用单租户口径，审计仍需 tenant_id 槽位。
DEFAULT_TENANT = "default"


class CandidateNotFound(ContentCandidateNotFound):
    """持久层候选不存在（路由映射 404）。"""


class CandidateNotReviewable(ContentCandidateNotReviewable):
    """候选非 pending_review（路由映射 409）。"""


def _default_producer() -> ContentProducer:
    """hub 已配置即走真实模型投影；否则确定性产出。

    W7-3：LOOM_CONTENT_REAL_LLM 门控随旧 env 下线——hub 配置本身就是开关，
    未配置时回退确定性产出，与历史默认一致。
    """
    if hub.is_hub_configured():
        return producers.LLMContentProducer()
    return producers.DeterministicProducer()


async def submit_candidate(
    session: AsyncSession,
    request: ContentRequest,
    *,
    actor_id: str | None = None,
    producer: ContentProducer | None = None,
) -> ContentCandidateRecord:
    if request.idempotency_key is not None:
        existing = await session.scalar(
            select(ContentCandidateRecord).where(
                ContentCandidateRecord.idempotency_key == request.idempotency_key
            )
        )
        if existing is not None:
            return existing

    assembly.check_banned(request)

    produced = await (producer or _default_producer()).produce(request)

    record = ContentCandidateRecord(
        candidate_id=str(uuid.uuid4()),
        product_id=request.product_id,
        channel=request.channel,
        content_type=request.content_type,
        body=produced.body,
        evidence_refs=produced.evidence_refs,
        status="pending_review",
        idempotency_key=request.idempotency_key,
    )
    session.add(record)
    await session.flush()

    await append_audit(
        session,
        tenant_id=DEFAULT_TENANT,
        actor_id=actor_id,
        actor_roles=None,
        action="content_base.candidate_submitted",
        entity_type="content_candidate",
        entity_id=record.candidate_id,
        detail={
            "product_id": record.product_id,
            "channel": record.channel,
            "content_type": record.content_type,
        },
    )
    return record


async def review_candidate(
    session: AsyncSession,
    candidate_id: str,
    decision: ReviewDecisionId,
    *,
    final_body: dict[str, Any] | None = None,
    note: str | None = None,
    reviewer_id: str | None = None,
) -> ContentCandidateRecord:
    record = await get_candidate(session, candidate_id)
    if record.status != "pending_review":
        raise CandidateNotReviewable(
            f"candidate is {record.status}, only pending_review accepts decisions"
        )

    if decision == "modified":
        if final_body is None:
            raise ContentRequestInvalid("decision=modified requires a replacement final_body")
        record.final_body = final_body
    elif decision == "confirmed":
        record.final_body = dict(record.body)
    # rejected：不固化 final_body。

    record.status = decision
    record.review_note = note
    record.reviewed_by = reviewer_id
    from app.core.content_base.types import now_utc

    record.reviewed_at = now_utc()

    await append_audit(
        session,
        tenant_id=DEFAULT_TENANT,
        actor_id=reviewer_id,
        actor_roles=None,
        action=f"content_base.candidate_{decision}",
        entity_type="content_candidate",
        entity_id=record.candidate_id,
        detail={"note": note},
    )
    return record


async def get_candidate(session: AsyncSession, candidate_id: str) -> ContentCandidateRecord:
    record = await session.get(ContentCandidateRecord, candidate_id)
    if record is None:
        raise CandidateNotFound(candidate_id)
    return record


async def list_candidates(
    session: AsyncSession,
    *,
    status: str | None = None,
    product_id: str | None = None,
    channel: str | None = None,
) -> list[ContentCandidateRecord]:
    stmt = select(ContentCandidateRecord)
    if status is not None:
        stmt = stmt.where(ContentCandidateRecord.status == status)
    if product_id is not None:
        stmt = stmt.where(ContentCandidateRecord.product_id == product_id)
    if channel is not None:
        stmt = stmt.where(ContentCandidateRecord.channel == channel)
    stmt = stmt.order_by(ContentCandidateRecord.created_at.desc())
    return list(await session.scalars(stmt))


def to_candidate(record: ContentCandidateRecord) -> ContentCandidate:
    """把持久记录映射为通用 ContentCandidate 契约。"""
    return ContentCandidate(
        id=record.candidate_id,
        body=record.body,
        product_id=record.product_id,
        channel=record.channel,
        content_type=cast(ContentTypeId, record.content_type),
        evidence_refs=list(record.evidence_refs),
        status=cast(CandidateStatus, record.status),
        idempotency_key=record.idempotency_key,
        final_body=record.final_body,
        review_note=record.review_note,
        reviewed_by=record.reviewed_by,
        reviewed_at=record.reviewed_at,
        created_at=record.created_at,
    )
