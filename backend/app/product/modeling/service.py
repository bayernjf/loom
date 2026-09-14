"""段2 C1 识别服务：信号权重/行业阈值配置、三分支判定、ops 待办、C7 四层兜底。

业务依据：Q1-Q7、Q68，docs/04 §2.3-2.6，docs/13 §1.1/1.2。
AI 不在本服务内：信号打分与 Layer4 字段生成由 WF-01 Skill 通道产出（随 M10 接入），
M2 只接收结构化结果并做确定性判定。
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.config_center.knobs import knob
from app.product.modeling import c1, c7
from app.product.modeling.models import (
    C1IndustryThreshold,
    C1Record,
    C1SignalWeight,
    C7Run,
    G1Category,
    G1CategoryTemplate,
    G2FieldCandidate,
    OpsTodo,
)
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import (
    G2Field,
    ProductIntakeApplication,
)
from app.product.product_intake.service import IntakeNotFound


class ConfigError(Exception):
    pass


class DefaultIndustryProtected(Exception):
    pass


class RecognitionNotAllowed(Exception):
    pass


class TodoNotFound(Exception):
    pass


class InvalidDecision(Exception):
    pass


class CategoryNotFound(Exception):
    pass


# ---------- Q2 信号权重 ----------

async def list_signal_weights(session: AsyncSession) -> Sequence[C1SignalWeight]:
    rows = await session.scalars(select(C1SignalWeight).order_by(C1SignalWeight.signal))
    return rows.all()


async def replace_signal_weights(session, rows, actor) -> list[C1SignalWeight]:
    enabled = {r.signal: float(r.weight) for r in rows if r.enabled}
    try:
        c1.validate_enabled_weights(enabled)
    except c1.WeightSumError as exc:
        raise ConfigError(str(exc)) from exc

    existing = {
        w.signal: w
        for w in (await session.scalars(select(C1SignalWeight))).all()
    }
    result: list[C1SignalWeight] = []
    for item in rows:
        row = existing.get(item.signal) or C1SignalWeight(signal=item.signal)
        row.signal_name = item.signal_name
        row.enabled = item.enabled
        row.weight = item.weight
        row.scoring_method = item.scoring_method
        session.add(row)
        result.append(row)

    await append_audit(
        session,
        tenant_id="_platform",
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="c1.signal_weights_update",
        entity_type="c1_signal_weights",
        entity_id="_",
        detail={"rows": [r.signal for r in rows], "enabled_sum": round(sum(enabled.values()), 4)},
    )
    await session.commit()
    return result


# ---------- Q7 行业阈值 CRUD ----------

async def list_industries(session: AsyncSession) -> Sequence[C1IndustryThreshold]:
    rows = await session.scalars(select(C1IndustryThreshold).order_by(C1IndustryThreshold.industry))
    return rows.all()


async def create_industry(session, item, actor) -> C1IndustryThreshold:
    row = C1IndustryThreshold(
        industry=item.industry,
        keywords=list(item.keywords),
        threshold=item.threshold,
        sensitive=item.sensitive,
        enabled=item.enabled,
        is_default=item.is_default,
    )
    session.add(row)
    await append_audit(
        session,
        tenant_id="_platform",
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="c1.industry_create",
        entity_type="c1_industry_thresholds",
        entity_id=item.industry,
        detail={"threshold": item.threshold, "sensitive": item.sensitive},
    )
    await session.commit()
    return row


async def patch_industry(session, industry, patch, actor) -> C1IndustryThreshold:
    row = await session.get(C1IndustryThreshold, industry)
    if row is None:
        raise CategoryNotFound(industry)
    for field in ("keywords", "threshold", "sensitive", "enabled"):
        value = getattr(patch, field)
        if value is not None:
            setattr(row, field, value)
    await append_audit(
        session,
        tenant_id="_platform",
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="c1.industry_update",
        entity_type="c1_industry_thresholds",
        entity_id=industry,
        detail={
            f: getattr(patch, f)
            for f in ("keywords", "threshold", "sensitive", "enabled")
            if getattr(patch, f) is not None
        },
    )
    await session.commit()
    return row


async def delete_industry(session, industry, actor) -> None:
    row = await session.get(C1IndustryThreshold, industry)
    if row is None:
        raise CategoryNotFound(industry)
    if row.is_default:
        raise DefaultIndustryProtected(f"{industry} is the non-deletable default tier (Q7)")
    await session.delete(row)
    await append_audit(
        session,
        tenant_id="_platform",
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="c1.industry_delete",
        entity_type="c1_industry_thresholds",
        entity_id=industry,
    )
    await session.commit()


# ---------- C1 三分支识别（Q1/Q3/Q4/Q5） ----------

async def _resolve_industry(session, explicit, profile) -> C1IndustryThreshold:
    rows = (await session.scalars(
        select(C1IndustryThreshold).where(C1IndustryThreshold.enabled.is_(True))
    )).all()
    by_name = {r.industry: r for r in rows}
    if explicit and explicit in by_name:
        return by_name[explicit]
    haystack = " ".join(str(v) for v in profile.values()).lower()
    for row in rows:
        if row.is_default:
            continue
        if any(kw.lower() in haystack for kw in row.keywords):
            return row
    default = next((r for r in rows if r.is_default), None)
    if default is None:
        raise ConfigError("default industry threshold tier is missing (Q7 requires general)")
    return default


async def submit_recognition(session, intake_id, body) -> tuple[C1Record, OpsTodo | None]:
    intake = await session.get(ProductIntakeApplication, intake_id)
    if intake is None:
        raise IntakeNotFound(intake_id)
    if intake.status != sm.AI_RECOGNIZING:
        raise RecognitionNotAllowed(
            f"C1 recognition only allowed in {sm.AI_RECOGNIZING}, current {intake.status}"
        )

    weights_rows = (await session.scalars(
        select(C1SignalWeight).where(C1SignalWeight.enabled.is_(True))
    )).all()
    weights = {w.signal: float(w.weight) for w in weights_rows}
    try:
        conf = c1.weighted_conf(body.signals, weights)
    except (c1.WeightSumError, c1.MissingSignalScore) as exc:
        raise ConfigError(str(exc)) from exc

    industry_row = await _resolve_industry(session, body.industry, intake.profile)
    decision = c1.decide_branch(
        conf=conf,
        threshold=industry_row.threshold,
        top_candidates=[c.model_dump() for c in body.candidates],
    )

    record = C1Record(
        tenant_id=intake.tenant_id,
        intake_id=intake_id,
        signals=dict(body.signals),
        conf=conf,
        industry=industry_row.industry,
        branch=decision.branch,
        top_candidates=[c.model_dump() for c in body.candidates],
        top_gap=decision.top_gap,
    )
    session.add(record)
    await session.flush()

    todo = None
    if decision.branch == c1.BRANCH_DIRECT_APPROVE:
        intake.status = sm.transition(intake.status, "wf01_confirm", body.actor.roles)
        intake.status = sm.transition(intake.status, "auto_confirm", body.actor.roles)
    elif decision.branch == c1.BRANCH_OPS_ASSIST:
        intake.status = sm.transition(intake.status, "wf01_confirm", body.actor.roles)
        now = datetime.now(UTC)
        todo = OpsTodo(
            tenant_id=intake.tenant_id,
            todo_type="ops_assist_category",
            entity_type="product_intake_application",
            entity_id=intake_id,
            detail={
                "record_id": record.record_id,
                "conf": conf,
                "top_candidates": record.top_candidates,
                "reason": "mid_confidence" if conf < industry_row.threshold else "contradiction",
            },
            due_at=now + timedelta(hours=knob("c1.ops_assist_sla_hours")),
        )
        session.add(todo)
    else:
        if not body.category_pending_id:
            raise InvalidDecision("cold_start branch requires a B2 category_pending_id")
        intake.category_pending_id = body.category_pending_id
        intake.status = sm.transition(intake.status, "wf01_cold_start", body.actor.roles)

    await append_audit(
        session,
        tenant_id=intake.tenant_id,
        actor_id=body.actor.id,
        actor_roles=body.actor.roles,
        action="c1.recognize",
        entity_type="product_intake_application",
        entity_id=intake_id,
        detail={
            "record_id": record.record_id,
            "conf": conf,
            "industry": industry_row.industry,
            "branch": decision.branch,
            "to": intake.status,
        },
    )
    await session.commit()
    return record, todo


async def ops_decide(session, intake_id, body) -> OpsTodo:
    intake = await session.get(ProductIntakeApplication, intake_id)
    if intake is None:
        raise IntakeNotFound(intake_id)
    if intake.status != sm.PENDING_CONFIRM:
        raise InvalidDecision(f"ops decision only allowed in {sm.PENDING_CONFIRM}")

    todo = (await session.scalars(
        select(OpsTodo)
        .where(
            OpsTodo.entity_id == intake_id,
            OpsTodo.todo_type == "ops_assist_category",
            OpsTodo.status.in_(["open", "escalated"]),
        )
        .order_by(OpsTodo.created_at.desc())
    )).first()
    if todo is None:
        raise TodoNotFound(intake_id)

    record = (await session.scalars(
        select(C1Record)
        .where(C1Record.intake_id == intake_id)
        .order_by(C1Record.created_at.desc())
    )).first()

    if body.decision == "select":
        if not body.category_id:
            raise InvalidDecision("select decision requires category_id")
        valid = {c["category_id"] for c in (record.top_candidates if record else [])}
        if body.category_id not in valid:
            raise InvalidDecision("category_id must be one of the AI top candidates")
        intake.status = sm.transition(intake.status, "ops_confirm", body.actor.roles)
        if record:
            record.selected_category_id = body.category_id
        todo.status = "resolved"
        todo.resolution = "selected"
        todo.resolved_at = datetime.now(UTC)
    elif body.decision == "reject_all":
        if not body.category_pending_id:
            raise InvalidDecision("reject_all requires a B2 category_pending_id")
        intake.category_pending_id = body.category_pending_id
        intake.status = sm.transition(intake.status, "to_cold_start", body.actor.roles)
        todo.status = "cancelled"
        todo.resolution = "reject_all_to_cold_start"
        todo.resolved_at = datetime.now(UTC)
    else:
        raise InvalidDecision(f"unknown decision {body.decision!r}")

    await append_audit(
        session,
        tenant_id=intake.tenant_id,
        actor_id=body.actor.id,
        actor_roles=body.actor.roles,
        action=f"c1.ops_{body.decision}",
        entity_type="product_intake_application",
        entity_id=intake_id,
        detail={"to": intake.status, "category_id": body.category_id},
    )
    await session.commit()
    return todo


async def escalate_due_todos(session, now: datetime | None = None) -> int:
    """Q4：开放待办超过 due_at 未处理 → escalated（主管/看板高亮）。

    薄包装：升级逻辑在 M10 通用 SLA 引擎（core.sla.engine，Q49/Q70），本函数
    保留模块入口与提交边界（既有端点/测试契约）。
    """
    from app.core.sla.engine import escalate_due_todos as _engine_sweep

    due = await _engine_sweep(session, now)
    await session.commit()
    return len(due)


# ---------- G1 类目树（最小切片；完整类目管理在 V3） ----------

async def create_category(session, body) -> G1Category:
    if body.parent_id and await session.get(G1Category, body.parent_id) is None:
        raise CategoryNotFound(body.parent_id)
    row = G1Category(name=body.name, parent_id=body.parent_id)
    session.add(row)
    await session.commit()
    return row


async def list_categories(session) -> Sequence[G1Category]:
    return (await session.scalars(select(G1Category).order_by(G1Category.created_at))).all()


async def upsert_template(session, category_id, body, actor) -> G1CategoryTemplate:
    category = await session.get(G1Category, category_id)
    if category is None:
        raise CategoryNotFound(category_id)
    fids = list(dict.fromkeys(body.field_list))  # 去重保序
    c7.validate_fids(fids)
    active_fids = set(
        (await session.scalars(
            select(G2Field.fid).where(G2Field.status == "active")
        )).all()
    )
    unknown = [fid for fid in fids if fid not in active_fids]
    if unknown:
        raise c7.IllegalFid(f"fids not found among active G2 fields: {unknown}")
    if body.status not in ("draft", "approved"):
        raise InvalidDecision(f"template status must be draft/approved, got {body.status}")

    template = await session.get(G1CategoryTemplate, category_id) or G1CategoryTemplate(
        category_id=category_id
    )
    template.field_list = fids
    template.status = body.status
    session.add(template)
    await append_audit(
        session,
        tenant_id="_platform",
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="c1.template_upsert",
        entity_type="g1_category_templates",
        entity_id=category_id,
        detail={"status": body.status, "fields": len(fids)},
    )
    await session.commit()
    return template


# ---------- C7 四层兜底（Q6/Q68） ----------

async def resolve_c7(session, intake_id, body, actor) -> C7Run:
    intake = await session.get(ProductIntakeApplication, intake_id)
    if intake is None:
        raise IntakeNotFound(intake_id)
    category = await session.get(G1Category, body.category_id)
    if category is None:
        raise CategoryNotFound(body.category_id)

    run = C7Run(tenant_id=intake.tenant_id, intake_id=intake_id, category_id=body.category_id)

    # Q68：任何字段入口都禁止 fid:'-'，与最终命中层无关（红旗正是 Layer1 缓存漏闸）。
    for proposal in body.l4_proposals:
        if proposal.get("fid") == c7.FORBIDDEN_FID:
            raise c7.IllegalFid("Layer4 proposal must not carry fid:'-' (Q68)")
        if not proposal.get("field_name"):
            raise InvalidDecision("Layer4 proposal requires field_name")

    # Layer1：本类目已有 approved 模板（缓存命中，0 token）。
    own = await session.get(G1CategoryTemplate, body.category_id)
    if own is not None and own.status == "approved":
        run.layer, run.field_list, run.detail = 1, list(own.field_list), {"via": "cache"}
    else:
        # Layer2：同父兄弟中 product_count 最大且模板 approved 者。
        sibling_rows = (await session.execute(
            select(G1Category, G1CategoryTemplate)
            .join(
                G1CategoryTemplate,
                G1CategoryTemplate.category_id == G1Category.category_id,
            )
            .where(
                G1Category.parent_id == category.parent_id,
                G1Category.category_id != body.category_id,
                G1CategoryTemplate.status == "approved",
            )
        )).all()
        siblings = [
            {
                "category_id": cat.category_id,
                "product_count": cat.product_count,
                "template_status": tpl.status,
                "field_list": list(tpl.field_list),
            }
            for cat, tpl in sibling_rows
        ]
        chosen = c7.pick_sibling(siblings)
        if chosen is not None:
            run.layer, run.field_list, run.detail = (
                2,
                list(chosen["field_list"]),
                {"via": "sibling", "inherited_from": chosen["category_id"]},
            )
        else:
            # Layer3：只能从 G2 active 挑（禁止发明新字段，Q68）。
            active_fids = list(
                (await session.scalars(
                    select(G2Field.fid).where(G2Field.status == "active")
                )).all()
            )
            c7.validate_fids(body.required_fids)
            ratio = c7.coverage(body.required_fids, active_fids)
            matched = [fid for fid in body.required_fids if fid in set(active_fids)]
            if ratio >= c7.layer3_coverage_floor():
                run.layer, run.field_list, run.detail = (
                    3,
                    matched,
                    {"via": "g2_pick", "coverage": ratio},
                )
            else:
                # Layer4：Skill 新字段进候选，深度审核 Gate 在段3（Q13）。
                candidate_ids: list[str] = []
                for proposal in body.l4_proposals:
                    candidate = G2FieldCandidate(
                        tenant_id=intake.tenant_id,
                        field_name=proposal["field_name"],
                        definition=proposal.get("definition"),
                        source_layer="c7_layer4",
                        source_route=proposal.get("source_route"),
                        confidence=proposal.get("confidence"),
                    )
                    session.add(candidate)
                    await session.flush()
                    candidate_ids.append(candidate.candidate_id)
                run.layer = 4
                run.field_list = matched + [
                    {"candidate_id": cid} for cid in candidate_ids
                ]
                run.detail = {
                    "via": "llm_new",
                    "coverage": ratio,
                    "candidate_ids": candidate_ids,
                }

    session.add(run)
    await append_audit(
        session,
        tenant_id=intake.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="c7.run",
        entity_type="product_intake_application",
        entity_id=intake_id,
        detail={"layer": run.layer, "category_id": body.category_id},
    )
    await session.commit()
    return run
