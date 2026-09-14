"""skill7 通道服务：投递（SkillRunLog）、候选裁决状态机、Q71 补货请求。

状态机（05 §2.3）：投递即 pending_review（ai_suggested 为生产者侧态，
不持久化【实现补，Q76】）→ confirmed/modified/rejected → applied/archived。
"""

from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.rbac import OPERATIONS, require_any_role
from app.core.skill7 import registry
from app.core.skill7.adapters import ADAPTERS
from app.core.skill7.models import SkillCandidate, SkillRun
from app.core.skill7.schemas import CandidateDecisionRequest, DeliverRunRequest

PWC_BUILDER = "PWC-BUILDER"
WF04 = "WF-04"


class CandidateNotReviewable(Exception):
    """候选当前状态不允许该裁决。"""


class InvalidCandidatePayload(Exception):
    """modified 未带 payload 或 payload 不通过适配器校验。"""


def _now() -> datetime:
    return datetime.now(UTC)


def _workflow_of_skill(skill_id: str) -> str | None:
    for wf_id, wf in registry.all_workflows().items():
        if any(step.get("skill_id") == skill_id for step in wf.get("skills", [])):
            return wf_id
    return None


def _validate_candidates(candidates) -> None:
    # 试点唯一适配器；其 payload 在投递时即用既有契约预校验，
    # 不把坏 payload 拖到人工裁决时才暴露。
    from app.product.condition.schemas import ComboItem

    for cand in candidates:
        if cand.target_type != "pwc_combo":
            raise InvalidCandidatePayload(f"unsupported target_type: {cand.target_type}")
        combos = cand.payload.get("combos")
        if not isinstance(combos, list) or not combos:
            raise InvalidCandidatePayload("payload.combos must be a non-empty list")
        try:
            for combo in combos:
                ComboItem(**combo)
        except ValidationError as exc:
            raise InvalidCandidatePayload(str(exc)) from exc


async def deliver_run(
    session: AsyncSession, body: DeliverRunRequest
) -> tuple[SkillRun, list[SkillCandidate]]:
    # Q76-5：投递归 operations；机器对机器 API Key 通道契约【待补】。
    require_any_role(body.actor, OPERATIONS)

    from app.product.product_intake.models import ProductSpace

    ps = await session.get(ProductSpace, body.product_space_id)
    if ps is None:
        raise ProductSpaceMissing(body.product_space_id)

    # 未注册 Skill 拒绝（注册表为唯一事实源，14 §2.2）。
    skill = registry.get_skill(body.skill_id)
    wf_id = body.wf_id or _workflow_of_skill(body.skill_id)
    if wf_id is None or body.skill_id not in {
        step.get("skill_id")
        for step in registry.get_workflow(wf_id).get("skills", [])
    }:
        raise registry.RegistryError(
            f"skill {body.skill_id} is not bound to workflow {wf_id!r}"
        )

    _validate_candidates(body.candidates)

    run = SkillRun(
        skill_id=body.skill_id,
        wf_id=wf_id,
        tenant_id=ps.tenant_id,
        product_space_id=ps.product_space_id,
        status="succeeded",
        source="delivery",
        input_payload=body.input,
        output_payload=body.output,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        confidence=body.confidence,
        created_by=body.actor.id,
    )
    session.add(run)
    await session.flush()

    created: list[SkillCandidate] = []
    for index, cand in enumerate(body.candidates):
        row = SkillCandidate(
            run_id=run.run_id,
            candidate_index=index,
            skill_id=body.skill_id,
            wf_id=wf_id,
            tenant_id=ps.tenant_id,
            product_space_id=ps.product_space_id,
            target_type=cand.target_type,
            payload=cand.payload,
            state="pending_review",
        )
        session.add(row)
        created.append(row)

    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=body.actor.id,
        actor_roles=body.actor.roles,
        action="skill7.run_delivered",
        entity_type="skill_run",
        entity_id=run.run_id,
        detail={
            "skill_id": body.skill_id,
            "wf_id": wf_id,
            "candidates": len(body.candidates),
            "model_tier": skill.get("model_tier") or None,
        },
    )
    return run, created


async def list_runs(
    session: AsyncSession,
    *,
    product_space_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[SkillRun]:
    stmt = select(SkillRun).order_by(desc(SkillRun.created_at), desc(SkillRun.run_id))
    if product_space_id:
        stmt = stmt.where(SkillRun.product_space_id == product_space_id)
    if status:
        stmt = stmt.where(SkillRun.status == status)
    return list((await session.scalars(stmt.limit(limit))).all())


async def list_candidates(
    session: AsyncSession,
    *,
    product_space_id: str | None = None,
    state: str | None = None,
    limit: int = 100,
) -> list[SkillCandidate]:
    stmt = select(SkillCandidate).order_by(
        SkillCandidate.created_at, SkillCandidate.candidate_id
    )
    if product_space_id:
        stmt = stmt.where(SkillCandidate.product_space_id == product_space_id)
    if state:
        stmt = stmt.where(SkillCandidate.state == state)
    return list((await session.scalars(stmt.limit(limit))).all())


async def decide_candidate(
    session: AsyncSession, candidate_id: str, body: CandidateDecisionRequest
) -> SkillCandidate:
    cand = await session.get(SkillCandidate, candidate_id)
    if cand is None:
        raise CandidateMissing(candidate_id)

    # 裁决角色沿用该 WF skill7 Gate 插槽配置（试点 WF-04 = product_reviewer）。
    require_any_role(body.actor, registry.review_role(cand.wf_id))

    if cand.state != "pending_review":
        raise CandidateNotReviewable(
            f"candidate is {cand.state}, only pending_review candidates accept decisions"
        )

    now = _now()
    if body.decision == "rejected":
        cand.state = "archived"
        cand.review_note = body.reason
        cand.reviewed_by = body.actor.id
        cand.reviewed_at = now
        await append_audit(
            session,
            tenant_id=cand.tenant_id,
            actor_id=body.actor.id,
            actor_roles=body.actor.roles,
            action="skill7.candidate_rejected",
            entity_type="skill_candidate",
            entity_id=cand.candidate_id,
            detail={"run_id": cand.run_id, "reason": body.reason},
        )
        return cand

    if body.decision == "modified":
        from app.product.condition.schemas import ComboItem

        if body.payload is None:
            raise InvalidCandidatePayload("decision=modified requires a replacement payload")
        try:
            combos = body.payload.get("combos")
            if not isinstance(combos, list) or not combos:
                raise InvalidCandidatePayload("payload.combos must be a non-empty list")
            for combo in combos:
                ComboItem(**combo)
        except (TypeError, ValidationError) as exc:
            raise InvalidCandidatePayload(str(exc)) from exc
        cand.payload = body.payload
        cand.human_modified = True

    adapter = ADAPTERS.get(cand.target_type)
    if adapter is None:  # 注册表投递侧已拦，防御性兜底。
        raise InvalidCandidatePayload(f"no adapter for target_type {cand.target_type}")
    applied_refs = await adapter(session, cand, body.actor)

    cand.state = "applied"
    cand.reviewed_by = body.actor.id
    cand.reviewed_at = now
    cand.review_note = body.reason
    cand.applied_refs = applied_refs
    await append_audit(
        session,
        tenant_id=cand.tenant_id,
        actor_id=body.actor.id,
        actor_roles=body.actor.roles,
        action="skill7.candidate_applied",
        entity_type="skill_candidate",
        entity_id=cand.candidate_id,
        detail={
            "run_id": cand.run_id,
            "decision": body.decision,
            "applied_refs": applied_refs,
        },
    )
    return cand


class ProductSpaceMissing(Exception):
    pass


class CandidateMissing(Exception):
    pass


async def maybe_request_restock(
    session: AsyncSession,
    *,
    tenant_id: str,
    product_space_id: str,
    ready_count: int,
    critical: int,
    cooldown_minutes: int,
    now: datetime | None = None,
) -> SkillRun | None:
    """Q71 critical→target 自动补货（Q76-4）。

    跌破 critical 且过防抖窗口 → 落一条 status=requested 的 SkillRun，
    不构造任何候选；外部投递迟到后正常走 pending_review。
    """
    now = now or _now()
    if ready_count >= critical:
        return None

    window_start = now - timedelta(minutes=cooldown_minutes)
    recent = (
        await session.scalars(
            select(SkillRun)
            .where(
                SkillRun.product_space_id == product_space_id,
                SkillRun.skill_id == PWC_BUILDER,
                SkillRun.source == "restock_auto",
                SkillRun.created_at >= window_start,
            )
            .order_by(desc(SkillRun.created_at))
            .limit(1)
        )
    ).first()
    if recent is not None:
        return None

    run = SkillRun(
        skill_id=PWC_BUILDER,
        wf_id=WF04,
        tenant_id=tenant_id,
        product_space_id=product_space_id,
        status="requested",
        source="restock_auto",
        input_payload={
            "reason": "pool_below_critical",
            "ready_count": ready_count,
            "critical": critical,
        },
        created_by="system",
    )
    session.add(run)
    await session.flush()  # 先取 uuid1 run_id，供审计 entity_id 关联。
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id="system",
        actor_roles=None,
        action="skill7.restock_requested",
        entity_type="skill_run",
        entity_id=run.run_id,
        detail={"ready_count": ready_count, "critical": critical},
    )
    return run
