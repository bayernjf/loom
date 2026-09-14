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


def _validate_payload(target_type: str, payload: dict) -> None:
    """投递/改单时按 target_type 做结构预校验（业务规则仍在适配器内跑）。"""
    if target_type == "pwc_combo":
        from app.product.condition.schemas import ComboItem

        combos = payload.get("combos")
        if not isinstance(combos, list) or not combos:
            raise InvalidCandidatePayload("payload.combos must be a non-empty list")
        try:
            for combo in combos:
                ComboItem(**combo)
        except ValidationError as exc:
            raise InvalidCandidatePayload(str(exc)) from exc
        return
    if target_type == "field_plan":
        from app.product.fieldpool.schemas import PlanSubmitRequest

        data = dict(payload)
        data.pop("actor", None)  # payload 是去 actor 的 PlanSubmitRequest 形态
        try:
            PlanSubmitRequest(
                **data, actor={"id": "_delivery_validation", "roles": []}
            )
        except ValidationError as exc:
            raise InvalidCandidatePayload(str(exc)) from exc
        return
    if target_type == "c1_recognition":
        # Q79：payload 是去 actor 的 C1RecognitionRequest 形态（CAT-RECOG 整结果）。
        from app.product.modeling.schemas import C1RecognitionRequest

        data = dict(payload)
        data.pop("actor", None)
        try:
            C1RecognitionRequest(
                **data, actor={"id": "_delivery_validation", "roles": []}
            )
        except ValidationError as exc:
            raise InvalidCandidatePayload(str(exc)) from exc
        return
    if target_type == "atom_batch":
        # Q80：payload 是去 actor 的 BatchSubmitRequest 形态（items + 可选 batch_size）；
        # 通道只接 AI 拓展批次，source 由适配器强制 "ai"（Q15 停拓仅对 AI 批次生效）。
        from app.product.atom.schemas import BatchSubmitRequest

        data = dict(payload)
        data.pop("actor", None)
        data.pop("source", None)
        try:
            BatchSubmitRequest(
                **data, source="ai", actor={"id": "_delivery_validation", "roles": []}
            )
        except ValidationError as exc:
            raise InvalidCandidatePayload(str(exc)) from exc
        return
    if target_type == "c7_layer4":
        # Q81：payload 是去 actor 的 C7ResolveRequest 形态
        # （category_id + required_fids + l4_proposals，TYPE-MATCH 整 C7 解析单候选）。
        from app.product.modeling.schemas import C7ResolveRequest

        data = dict(payload)
        data.pop("actor", None)
        try:
            C7ResolveRequest(
                **data, actor={"id": "_delivery_validation", "roles": []}
            )
        except ValidationError as exc:
            raise InvalidCandidatePayload(str(exc)) from exc
        return
    raise InvalidCandidatePayload(f"unsupported target_type: {target_type}")


def _validate_delivery(wf_id: str, skill_id: str, candidates) -> str:
    # Q78：投递校验以 WF 步骤声明的 candidate_target 为准（不再硬编码 pwc_combo）。
    step = registry.producer_step_for(wf_id, skill_id)
    if step is None:
        raise InvalidCandidatePayload(
            f"skill {skill_id} is not declared as a candidate producer in {wf_id}"
        )
    expected_target = step["candidate_target"]
    if not candidates:
        raise InvalidCandidatePayload("candidates must be a non-empty list")
    # Q79：单候选约束由步骤声明 single_candidate 驱动（field_plan/c1_recognition）。
    if step.get("single_candidate") and len(candidates) != 1:
        raise InvalidCandidatePayload(
            f"{expected_target} delivery must contain exactly one whole-result candidate"
        )
    for cand in candidates:
        if cand.target_type != expected_target:
            raise InvalidCandidatePayload(
                f"candidate target_type {cand.target_type!r} does not match declared "
                f"candidate_target {expected_target!r} of {wf_id}/{skill_id}"
            )
        _validate_payload(cand.target_type, cand.payload)
    return expected_target


async def deliver_run(
    session: AsyncSession, body: DeliverRunRequest
) -> tuple[SkillRun, list[SkillCandidate]]:
    # Q76-5：投递归 operations；机器对机器 API Key 通道契约【待补】。
    require_any_role(body.actor, OPERATIONS)
    return await _persist_delivery(session, body, source="delivery")


async def deliver_generated_run(
    session: AsyncSession,
    body: DeliverRunRequest,
    *,
    model_id: str,
    input_cost,
    output_cost,
    currency_code: str | None,
) -> tuple[SkillRun, list[SkillCandidate]]:
    """Q82-2：进程内真 LLM 调用后的机器投递。

    与人工外部投递共用同一条通道与全部校验，但 system actor 不持任何角色
    （Q66），source=llm_auto 以区别外部投递；候选同样落 pending_review 过人工 Gate。
    """
    return await _persist_delivery(
        session,
        body,
        source="llm_auto",
        model_id=model_id,
        input_cost=input_cost,
        output_cost=output_cost,
        currency_code=currency_code,
    )


async def _persist_delivery(
    session: AsyncSession,
    body: DeliverRunRequest,
    *,
    source: str,
    model_id: str | None = None,
    input_cost=None,
    output_cost=None,
    currency_code: str | None = None,
) -> tuple[SkillRun, list[SkillCandidate]]:
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

    expected_target = _validate_delivery(wf_id, body.skill_id, body.candidates)

    # Q79-4/Q81：锚点按 WF 归属二选一——c1_recognition/c7_layer4（段2）挂 intake，
    # 其余（WF-02/WF-03/WF-04）挂 ProductSpace。
    intake_anchor = expected_target in {"c1_recognition", "c7_layer4"}
    if intake_anchor:
        if body.intake_id is None or body.product_space_id is not None:
            raise InvalidCandidatePayload(
                f"{expected_target} delivery must use intake_id anchor"
            )
        from app.product.product_intake.models import ProductIntakeApplication
        from app.product.product_intake.service import IntakeNotFound

        intake = await session.get(ProductIntakeApplication, body.intake_id)
        if intake is None:
            raise IntakeNotFound(body.intake_id)
        tenant_id = intake.tenant_id
        product_space_id = None
        intake_id = intake.intake_id
    else:
        if body.product_space_id is None or body.intake_id is not None:
            raise InvalidCandidatePayload(
                f"{expected_target} delivery must use product_space_id anchor"
            )
        from app.product.product_intake.models import ProductSpace

        ps = await session.get(ProductSpace, body.product_space_id)
        if ps is None:
            raise ProductSpaceMissing(body.product_space_id)
        tenant_id = ps.tenant_id
        product_space_id = ps.product_space_id
        intake_id = None

    run = SkillRun(
        skill_id=body.skill_id,
        wf_id=wf_id,
        tenant_id=tenant_id,
        product_space_id=product_space_id,
        intake_id=intake_id,
        status="succeeded",
        source=source,
        input_payload=body.input,
        output_payload=body.output,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        model_id=model_id,
        input_cost=input_cost,
        output_cost=output_cost,
        currency_code=currency_code,
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
            tenant_id=tenant_id,
            product_space_id=product_space_id,
            intake_id=intake_id,
            target_type=cand.target_type,
            payload=cand.payload,
            state="pending_review",
        )
        session.add(row)
        created.append(row)

    await append_audit(
        session,
        tenant_id=tenant_id,
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
            "model_id": model_id,
            "source": source,
            "anchor": "intake" if intake_anchor else "product_space",
        },
    )
    return run, created


async def list_runs(
    session: AsyncSession,
    *,
    product_space_id: str | None = None,
    intake_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[SkillRun]:
    stmt = select(SkillRun).order_by(desc(SkillRun.created_at), desc(SkillRun.run_id))
    if product_space_id:
        stmt = stmt.where(SkillRun.product_space_id == product_space_id)
    if intake_id:
        stmt = stmt.where(SkillRun.intake_id == intake_id)
    if status:
        stmt = stmt.where(SkillRun.status == status)
    return list((await session.scalars(stmt.limit(limit))).all())


async def list_candidates(
    session: AsyncSession,
    *,
    product_space_id: str | None = None,
    intake_id: str | None = None,
    state: str | None = None,
    limit: int = 100,
) -> list[SkillCandidate]:
    stmt = select(SkillCandidate).order_by(
        SkillCandidate.created_at, SkillCandidate.candidate_id
    )
    if product_space_id:
        stmt = stmt.where(SkillCandidate.product_space_id == product_space_id)
    if intake_id:
        stmt = stmt.where(SkillCandidate.intake_id == intake_id)
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
        if body.payload is None:
            raise InvalidCandidatePayload("decision=modified requires a replacement payload")
        _validate_payload(cand.target_type, body.payload)
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
