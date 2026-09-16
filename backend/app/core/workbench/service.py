"""统一审核工作台服务（Q70 一期，Q93/C1.37）。

列表：skill7 候选跨 target_type 统一出队，风险归一见 risk.py，
按 risk_rank DESC, created_at ASC 排序；批量通过复用 skill7
decide_candidate（confirmed），每条仍过所属 WF Gate 角色与适配器全部规则。
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.config_center.knobs import knob
from app.core.rbac import PermissionDenied, require_any_role
from app.core.skill7 import registry
from app.core.skill7 import service as skill7_service
from app.core.skill7.models import SkillCandidate, SkillRun
from app.core.skill7.schemas import CandidateDecisionRequest
from app.core.workbench import risk
from app.product.modeling.models import C1IndustryThreshold

BATCH_CONFIDENCE_KEY = "review.batch_pass_confidence"


class WorkbenchCandidateMissing(Exception):
    """批量请求中存在不存在的候选 id。"""


class BatchCandidateNotPending(Exception):
    """批量通过只接受 pending_review 候选。"""

    def __init__(self, candidate_id: str, state: str):
        self.candidate_id = candidate_id
        self.state = state
        super().__init__(f"candidate {candidate_id} is {state}, not pending_review")


class BatchGateRejected(Exception):
    """候选未过批量门槛（置信度/风险）。"""

    def __init__(self, candidate_id: str, reason: str):
        self.candidate_id = candidate_id
        self.reason = reason
        super().__init__(f"candidate {candidate_id} not batch-eligible: {reason}")


def queue_roles() -> set[str]:
    """所有 WF 的 skill7 Gate 角色并集（数据驱动，YAML 加角色自动生效）。"""
    return {
        gate["role"]
        for wf in registry.all_workflows().values()
        for gate in wf.get("gates", [])
        if gate.get("channel") == "skill7"
    }


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        # SQLite 回读丢时区；PG 列存 aware UTC。
        value = value.replace(tzinfo=UTC)
    return value


async def _enrich(
    session: AsyncSession, candidates: list[SkillCandidate]
) -> dict[str, dict]:
    run_ids = {cand.run_id for cand in candidates}
    confidence_by_run: dict[str, float | None] = {}
    if run_ids:
        rows = await session.execute(
            select(SkillRun.run_id, SkillRun.confidence).where(
                SkillRun.run_id.in_(run_ids)
            )
        )
        confidence_by_run = {row[0]: row[1] for row in rows}

    industries = {
        cand.payload.get("industry")
        for cand in candidates
        if cand.target_type == "c1_recognition" and cand.payload.get("industry")
    }
    sensitive: set[str] = set()
    if industries:
        rows = await session.scalars(
            select(C1IndustryThreshold.industry).where(
                C1IndustryThreshold.industry.in_(industries),
                C1IndustryThreshold.sensitive.is_(True),
            )
        )
        sensitive = set(rows)

    enriched: dict[str, dict] = {}
    for cand in candidates:
        level, reason = risk.derive_risk(
            cand.target_type, cand.payload, sensitive_industries=sensitive
        )
        enriched[cand.candidate_id] = {
            "confidence": confidence_by_run.get(cand.run_id),
            "risk_level": level,
            "risk_rank": risk.RISK_RANK[level],
            "risk_reason": reason,
        }
    return enriched


def _is_batch_eligible(meta: dict, threshold: float) -> tuple[bool, str | None]:
    confidence = meta["confidence"]
    if confidence is None:
        return False, "run confidence missing"
    if confidence <= threshold:
        return False, f"confidence {confidence} <= {threshold}"
    if meta["risk_rank"] >= risk.BATCH_RISK_CEILING:
        return False, f"risk_level {meta['risk_level']} requires single review"
    return True, None


def _candidate_view(cand: SkillCandidate, meta: dict, *, now: datetime) -> dict:
    created_at = _aware(cand.created_at)
    reviewed_at = _aware(cand.reviewed_at)
    eligible, _ = _is_batch_eligible(meta, knob(BATCH_CONFIDENCE_KEY))
    return {
        "candidate_id": cand.candidate_id,
        "run_id": cand.run_id,
        "candidate_index": cand.candidate_index,
        "skill_id": cand.skill_id,
        "wf_id": cand.wf_id,
        "tenant_id": cand.tenant_id,
        "product_space_id": cand.product_space_id,
        "intake_id": cand.intake_id,
        "target_type": cand.target_type,
        "payload": cand.payload,
        "state": cand.state,
        "human_modified": cand.human_modified,
        "review_note": cand.review_note,
        "reviewed_by": cand.reviewed_by,
        "reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
        "created_at": created_at.isoformat() if created_at else None,
        "wait_seconds": int((now - created_at).total_seconds())
        if cand.state == "pending_review" and created_at is not None
        else None,
        "confidence": meta["confidence"],
        "risk_level": meta["risk_level"],
        "risk_rank": meta["risk_rank"],
        "risk_reason": meta["risk_reason"],
        "batch_eligible": eligible if cand.state == "pending_review" else False,
    }


async def list_queue(
    session: AsyncSession,
    *,
    state: str,
    target_types: list[str] | None,
    wf_id: str | None,
    risk_level: str | None,
    limit: int,
    offset: int,
) -> dict:
    stmt = select(SkillCandidate).where(SkillCandidate.state == state)
    if target_types:
        stmt = stmt.where(SkillCandidate.target_type.in_(target_types))
    if wf_id:
        stmt = stmt.where(SkillCandidate.wf_id == wf_id)
    candidates = list((await session.scalars(stmt)).all())

    now = datetime.now(UTC)
    enriched = await _enrich(session, candidates)
    ranked = [
        (cand, enriched[cand.candidate_id])
        for cand in candidates
        if risk_level is None
        or enriched[cand.candidate_id]["risk_level"] == risk_level
    ]
    ranked.sort(
        key=lambda pair: (
            -pair[1]["risk_rank"],
            _aware(pair[0].created_at) or now,
            pair[0].candidate_id,
        )
    )
    page = ranked[offset : offset + limit]
    return {
        "total": len(ranked),
        "limit": limit,
        "offset": offset,
        "batch_pass_confidence": knob(BATCH_CONFIDENCE_KEY),
        "candidates": [_candidate_view(cand, meta, now=now) for cand, meta in page],
    }


async def batch_approve(
    session: AsyncSession, *, candidate_ids: list[str], reason: str | None, actor
) -> list[SkillCandidate]:
    candidates: list[SkillCandidate | None] = [
        await session.get(SkillCandidate, candidate_id)
        for candidate_id in candidate_ids
    ]
    missing = [
        candidate_id
        for candidate_id, cand in zip(candidate_ids, candidates, strict=True)
        if cand is None
    ]
    if missing:
        raise WorkbenchCandidateMissing(str(missing))

    # 预检阶段不产生任何写入：状态 → 角色 → 批量门槛。
    for cand in candidates:
        if cand.state != "pending_review":
            raise BatchCandidateNotPending(cand.candidate_id, cand.state)
    for cand in candidates:
        # 逐条按所属 WF Gate 角色校验；混角色批整批拒绝。
        try:
            require_any_role(actor, registry.review_role(cand.wf_id))
        except PermissionDenied as exc:
            raise PermissionDenied(
                f"candidate {cand.candidate_id} ({cand.wf_id}): {exc}"
            ) from exc

    enriched = await _enrich(session, candidates)
    threshold = knob(BATCH_CONFIDENCE_KEY)
    for cand in candidates:
        eligible, why = _is_batch_eligible(enriched[cand.candidate_id], threshold)
        if not eligible:
            raise BatchGateRejected(cand.candidate_id, why)

    decision = CandidateDecisionRequest(
        decision="confirmed", reason=reason, actor=actor
    )
    applied: list[SkillCandidate] = []
    for cand in candidates:
        applied.append(
            await skill7_service.decide_candidate(
                session, cand.candidate_id, decision
            )
        )

    await append_audit(
        session,
        tenant_id=applied[0].tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="workbench.batch_approved",
        entity_type="skill_candidate",
        entity_id=applied[0].candidate_id,
        detail={"candidate_ids": [cand.candidate_id for cand in applied]},
    )
    return applied
