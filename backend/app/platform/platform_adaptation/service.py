"""段7/8 静态底表服务（08 M11）：发布位/规则/默认值/fit 权重/PCP。

角色口径：后台档案 CRUD = operations（Q35）；所有写操作 writeAudit。
"""

import json
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.audit import append_audit
from app.core.config_center.knobs import knob
from app.core.model_registry import gateway
from app.core.model_registry.seeds import SCENE_PLATFORM_ADAPTER
from app.decision.layer_strategy.models import Package
from app.platform.platform_adaptation import pa_rules
from app.platform.platform_adaptation.models import (
    GoalFitWeight,
    PcpRecalcCandidate,
    PcpTemplate,
    PcpWeightTable,
    PlatformAdapterCandidate,
    PlatformDynamicEvent,
    PlatformRule,
    PublishSlot,
    SlotTypeDefault,
)
from app.product.condition.models import ContentGoal
from app.product.modeling.models import OpsTodo
from app.product.product_intake.models import ProductSpace
from app.product.whitelist_center.models import PwsSnapshot

PLATFORM_TENANT = "_platform"
ROLE_OPERATIONS = "operations"

# Q42 单项单次重算幅度（配置中心 platform.recalc_step，默认 0.05）。
RECALC_STEP_KEY = "platform.recalc_step"
SOURCE_MANUAL = "manual"
CAND_PENDING = "pending"
CAND_APPROVED = "approved"
CAND_REJECTED = "rejected"

# ---- Q294：PCP 每周重算提醒（SweepScheduler 第 6 作业，只提醒、不产权重）----
# 提醒待办类型/实体；审计动作与 SLA 升级动作（升级沿用引擎默认 sla.todo_escalated）。
TODO_TYPE_PCP_WEEKLY_RECALC = "pcp_weekly_recalc"
ENTITY_TYPE_PCP = "pcp_weight_table"
RECALC_TODO_ACTION = "signal.pcp_weekly_recalc_todo"
# 周节奏与提醒截止时长（配置中心热更；默认值见 seeds.py，Q294 甲案）。
WEEKDAY_KEY = "platform.recalc_weekday"
HOUR_KEY = "platform.recalc_hour"
TZ_OFFSET_KEY = "platform.recalc_tz_offset_hours"
TODO_DUE_DAYS_KEY = "platform.recalc_todo_due_days"
CYCLE = timedelta(days=7)


class RoleNotAllowed(Exception):
    pass


class SlotNotFound(Exception):
    pass


class SlotCodeTaken(Exception):
    pass


class ValidationFailed(Exception):
    def __init__(self, violations: list[str]):
        super().__init__(str(violations))
        self.violations = violations


class RuleNotFound(Exception):
    pass


class RuleConflict(Exception):
    def __init__(self, conflicts: list[PlatformRule]):
        super().__init__("conflicting rules")
        self.conflicts = conflicts


class GoalNotFound(Exception):
    pass


class TemplateNotFound(Exception):
    pass


class PcpNotFound(Exception):
    pass


class PcpExists(Exception):
    pass


class EventNotFound(Exception):
    pass


class EventPeriodInvalid(Exception):
    pass


class PendingCandidateExists(Exception):
    pass


class RecalcStepExceeded(Exception):
    """Q42：单项变化超出 platform.recalc_step（默认 ±0.05）；重大变化走人工直编通道。"""

    def __init__(self, message: str):
        super().__init__(message)


class PwsSnapshotNotFound(Exception):
    """Q296 甲：预览口引用的 PWS 快照不存在（404，与 PT 约束 7 的「无 frozen」缺失
    形状区分——前者是输入错误，后者是协议内的正常缺失结果）。"""


class AdapterCandidateNotFound(Exception):
    """Q300：adapter 候选不存在或已裁决（404，照 Q259 EventNotFound 口径）。"""


class AdapterDecisionRequired(Exception):
    """Q300：reject 必须给 reason（照 Q259 reject_candidate）。"""


def _now() -> datetime:
    return datetime.now(UTC)


def _require_ops(actor) -> None:
    if ROLE_OPERATIONS not in actor.roles:
        raise RoleNotAllowed("requires operations role")


# ---------- 发布位档案（Q35） ----------

async def list_slots(
    session, *, platform: str | None = None, status: str | None = "active"
) -> list[PublishSlot]:
    stmt = select(PublishSlot)
    if platform:
        stmt = stmt.where(PublishSlot.platform == platform)
    if status:
        stmt = stmt.where(PublishSlot.status == status)
    return list((await session.scalars(stmt.order_by(PublishSlot.code))).all())


async def create_slot(session, body, actor) -> PublishSlot:
    _require_ops(actor)
    taken = (
        await session.scalars(
            select(PublishSlot).where(PublishSlot.code == body.item.code)
        )
    ).first()
    if taken is not None:
        raise SlotCodeTaken(body.item.code)
    slot = PublishSlot(
        **body.item.model_dump(),
        # Q35：四维分为主观字段，明示"人工评估"。
        score_source="manual_eval",
        created_by=actor.id,
    )
    session.add(slot)
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="slot.create",
        entity_type="publish_slot",
        entity_id=slot.slot_id,
        detail={"code": slot.code},
    )
    return slot


async def update_slot(session, slot_id: str, body, actor) -> PublishSlot:
    _require_ops(actor)
    slot = await session.get(PublishSlot, slot_id)
    if slot is None:
        raise SlotNotFound(slot_id)
    clash = (
        await session.scalars(
            select(PublishSlot).where(
                PublishSlot.code == body.item.code,
                PublishSlot.slot_id != slot_id,
            )
        )
    ).first()
    if clash is not None:
        raise SlotCodeTaken(body.item.code)
    # Q299 fit 人工校准闭环：四维分（0-100 主观静态分）的 before/after 必须进
    # slot.update 审计，使运营对 fit_score 输入的每次校准可追溯（不新增端点、
    # 不改变 fit_score 派生时现算的口径；本切片是「人工校准」不是「自学习」）。
    dims_before = {dim: getattr(slot, dim) for dim in pa_rules.FIT_DIMS}
    for key, value in body.item.model_dump().items():
        setattr(slot, key, value)
    slot.updated_at = _now()
    dims_after = {dim: getattr(slot, dim) for dim in pa_rules.FIT_DIMS}
    dim_changes = {
        dim: {"before": dims_before[dim], "after": dims_after[dim]}
        for dim in pa_rules.FIT_DIMS
        if dims_before[dim] != dims_after[dim]
    }
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="slot.update",
        entity_type="publish_slot",
        entity_id=slot_id,
        detail={"code": slot.code, "fit_dim_changes": dim_changes},
    )
    return slot


async def archive_slot(session, slot_id: str, actor) -> None:
    _require_ops(actor)
    slot = await session.get(PublishSlot, slot_id)
    if slot is None:
        raise SlotNotFound(slot_id)
    slot.status = "archived"
    slot.updated_at = _now()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="slot.archive",
        entity_type="publish_slot",
        entity_id=slot_id,
        detail={"code": slot.code},
    )


async def fit_score(session, slot_id: str, goal: str) -> dict:
    """Q34 派生值（不落库）：fit_score = Σ(维度分 × 目的权重)。

    目的未配权重矩阵【原文未给出的目的】→ fit_score=None + incomplete 旗标，
    不凑分（对齐 Q22b AI 失败不凑分精神）。
    Q296 甲加法扩展：回带 ``breakdown`` 四行分项（dim/score/weight/contribution，
    与聚合函数同权重同序，Σ(contribution) == fit_score 可自校验；incomplete 时
    weight/contribution 为 None——分可见、不造聚合）。
    """
    slot = await session.get(PublishSlot, slot_id)
    if slot is None:
        raise SlotNotFound(slot_id)
    row = await session.get(GoalFitWeight, goal)
    if row is None:
        return {
            "slot_id": slot_id,
            "goal": goal,
            "fit_score": None,
            "incomplete": True,
            "breakdown": [
                {"dim": dim, "score": getattr(slot, dim), "weight": None, "contribution": None}
                for dim in pa_rules.FIT_DIMS
            ],
        }
    return {
        "slot_id": slot_id,
        "goal": goal,
        "fit_score": pa_rules.compute_fit_score(slot, row.weights),
        "incomplete": False,
        "breakdown": pa_rules.fit_score_breakdown(slot, row.weights),
    }


# ---------- Q34 目的权重矩阵 ----------

async def list_fit_weights(session) -> list[GoalFitWeight]:
    return list((await session.scalars(select(GoalFitWeight).order_by(GoalFitWeight.goal))).all())


async def put_fit_weights(session, body, actor) -> GoalFitWeight:
    _require_ops(actor)
    goal = await session.get(ContentGoal, body.goal)
    if goal is None or goal.status != "active":
        raise GoalNotFound(body.goal)
    violations = pa_rules.validate_fit_weights(body.weights)
    if violations:
        raise ValidationFailed(violations)
    row = await session.get(GoalFitWeight, body.goal)
    weights_before = dict(row.weights) if row is not None else None
    if row is None:
        row = GoalFitWeight(goal=body.goal, weights=body.weights, updated_by=actor.id)
        session.add(row)
    else:
        row.weights = body.weights
        row.updated_by = actor.id
        row.updated_at = _now()
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="fit_weights.put",
        entity_type="goal_fit_weight",
        entity_id=body.goal,
        detail={
            "weights": body.weights,
            # Q299：目的权重矩阵也是 fit_score 的人工校准面，before/after 留痕。
            "weights_before": weights_before,
        },
    )
    return row


# ---------- 平台规则（Q36） ----------

async def list_rules(
    session,
    *,
    platform: str | None = None,
    slot_type: str | None = None,
    status: str | None = "active",
) -> list[PlatformRule]:
    stmt = select(PlatformRule)
    if platform:
        stmt = stmt.where(PlatformRule.platform == platform)
    if slot_type:
        stmt = stmt.where(PlatformRule.slot_type == slot_type)
    if status:
        stmt = stmt.where(PlatformRule.status == status)
    return list((await session.scalars(stmt.order_by(PlatformRule.created_at))).all())


def _validate_rule_item(item) -> None:
    violations = pa_rules.validate_selector(
        item.selector_level, item.platform, item.slot_type, item.slot_id
    )
    if item.effect not in (pa_rules.EFFECT_BLOCKED, pa_rules.EFFECT_PARTIAL):
        violations.append(f"unknown_effect:{item.effect}")
    if violations:
        raise ValidationFailed(violations)


async def create_rule(session, body, actor) -> PlatformRule:
    _require_ops(actor)
    _validate_rule_item(body.item)
    candidate = PlatformRule(**body.item.model_dump(), created_by=actor.id)
    existing = list((await session.scalars(select(PlatformRule))).all())
    conflicts = pa_rules.find_conflicts(existing, candidate)
    if conflicts and not body.overwrite:
        # Q36：当场提示"覆盖旧规则 / 放弃保存"——API 化为 409 + overwrite 重发。
        raise RuleConflict(conflicts)
    for old in conflicts:
        old.status = "archived"
    session.add(candidate)
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="rule.create",
        entity_type="platform_rule",
        entity_id=candidate.rule_id,
        detail={
            "level": candidate.selector_level,
            "effect": candidate.effect,
            "overwritten": [r.rule_id for r in conflicts],
        },
    )
    return candidate


async def archive_rule(session, rule_id: str, actor) -> None:
    _require_ops(actor)
    rule = await session.get(PlatformRule, rule_id)
    if rule is None:
        raise RuleNotFound(rule_id)
    rule.status = "archived"
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="rule.archive",
        entity_type="platform_rule",
        entity_id=rule_id,
        detail={"level": rule.selector_level, "effect": rule.effect},
    )


async def _match_rule_rows(
    session,
    *,
    platform: str,
    slot_type: str,
    slot_id: str | None = None,
    country: str | None = None,
) -> list[PlatformRule]:
    """Q36 四层选择器的行级命中（match_rules 与 Q296 预览口共用同一份匹配语义）。"""
    rows = list(
        (
            await session.scalars(
                select(PlatformRule).where(PlatformRule.status == "active")
            )
        ).all()
    )
    return [
        r
        for r in rows
        if (r.platform is None or r.platform == platform)
        and (r.slot_type is None or r.slot_type == slot_type)
        and (r.slot_id is None or r.slot_id == slot_id)
        and (r.country is None or r.country == country)
    ]


async def match_rules(
    session,
    *,
    platform: str,
    slot_type: str,
    slot_id: str | None = None,
    country: str | None = None,
) -> dict:
    """按格子命中规则并给出 Q36 裁决（供段7 适配与调试查看）。"""
    matched = await _match_rule_rows(
        session, platform=platform, slot_type=slot_type, slot_id=slot_id, country=country
    )
    return {
        "effect": pa_rules.resolve_effect(matched),
        "matched_rule_ids": [r.rule_id for r in matched],
    }


# ---------- slotType 默认值 ----------

async def list_slot_type_defaults(session) -> list[SlotTypeDefault]:
    return list(
        (await session.scalars(select(SlotTypeDefault).order_by(SlotTypeDefault.slot_type))).all()
    )


async def put_slot_type_default(session, body, actor) -> SlotTypeDefault:
    _require_ops(actor)
    if (
        body.daily_limit_min is not None
        and body.daily_limit_max is not None
        and body.daily_limit_min > body.daily_limit_max
    ):
        raise ValidationFailed(["daily_limit_min_gt_max"])
    row = await session.get(SlotTypeDefault, body.slot_type)
    if row is None:
        row = SlotTypeDefault(
            slot_type=body.slot_type,
            daily_limit_min=body.daily_limit_min,
            daily_limit_max=body.daily_limit_max,
            defaults=body.defaults,
            updated_by=actor.id,
        )
        session.add(row)
    else:
        row.daily_limit_min = body.daily_limit_min
        row.daily_limit_max = body.daily_limit_max
        row.defaults = body.defaults
        row.updated_by = actor.id
        row.updated_at = _now()
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="slot_type_default.put",
        entity_type="slot_type_default",
        entity_id=body.slot_type,
        detail={"daily_limit_min": body.daily_limit_min, "daily_limit_max": body.daily_limit_max},
    )
    return row


# ---------- 段8 PCP 权重 ----------

async def list_templates(session) -> list[PcpTemplate]:
    return list(
        (
            await session.scalars(
                select(PcpTemplate).where(PcpTemplate.status == "active").order_by(PcpTemplate.code)
            )
        ).all()
    )


async def create_pcp(session, product_space_id: str, body, actor) -> PcpWeightTable:
    _require_ops(actor)
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise PcpNotFound(product_space_id)
    existing = (
        await session.scalars(
            select(PcpWeightTable).where(
                PcpWeightTable.product_space_id == product_space_id,
                PcpWeightTable.platform == body.platform,
                PcpWeightTable.status == "active",
            )
        )
    ).first()
    if existing is not None:
        raise PcpExists(f"{product_space_id}/{body.platform}")
    if body.weights is not None:
        weights = body.weights
        template_code = None
    else:
        template = (
            await session.scalars(
                select(PcpTemplate).where(
                    PcpTemplate.code == body.template_code,
                    PcpTemplate.status == "active",
                )
            )
        ).first() if body.template_code else None
        if template is None:
            raise TemplateNotFound(body.template_code)
        weights = dict(template.weights)
        template_code = template.code
    violations = pa_rules.validate_weights_17(weights)
    if violations:
        raise ValidationFailed(violations)
    pcp = PcpWeightTable(
        tenant_id=ps.tenant_id,
        product_space_id=product_space_id,
        platform=body.platform,
        template_code=template_code,
        weights=weights,
        created_by=actor.id,
    )
    session.add(pcp)
    await session.flush()
    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pcp.create",
        entity_type="pcp_weight_table",
        entity_id=pcp.pcp_id,
        detail={"platform": pcp.platform, "template_code": template_code},
    )
    return pcp


async def update_pcp(session, pcp_id: str, body, actor) -> PcpWeightTable:
    """Q42 人工直接编辑通道：无幅度限制，有审计；AI 重算通道随 V2。"""
    _require_ops(actor)
    pcp = await session.get(PcpWeightTable, pcp_id)
    if pcp is None:
        raise PcpNotFound(pcp_id)
    violations = pa_rules.validate_weights_17(body.weights)
    if violations:
        raise ValidationFailed(violations)
    before = dict(pcp.weights)
    pcp.weights = body.weights
    pcp.template_code = None
    pcp.updated_at = _now()
    await append_audit(
        session,
        tenant_id=pcp.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pcp.update",
        entity_type="pcp_weight_table",
        entity_id=pcp_id,
        detail={"before": before, "after": body.weights},
    )
    # Q264（Q45 重配载体甲，PCP 触发源）：PCP 权重表更新即触发重配走 Gate——
    # 对该 PS×platform 下全部 active 三包各写一条 package.reuse_threshold_reached
    # 审计（trigger=pcp_update，detail 带 pcp_id），复用 Q263 审计通道作信号源；
    # 不区分模板切换/微调（裁决口径 docs/design-p2-package-reuse-reconfig.md §4 裁点 3）。
    active = (
        await session.scalars(
            select(Package).where(
                Package.product_space_id == pcp.product_space_id,
                Package.platform == pcp.platform,
                Package.status == "active",
            )
        )
    ).all()
    for pkg in active:
        await append_audit(
            session,
            tenant_id=pcp.tenant_id,
            actor_id=actor.id,
            actor_roles=actor.roles,
            action="package.reuse_threshold_reached",
            entity_type="package",
            entity_id=pkg.package_id,
            detail={
                "trigger": "pcp_update",
                "kind": pkg.kind,
                "platform": pcp.platform,
                "goal": pkg.goal,
                "pcp_id": pcp_id,
                "usage_count": pkg.usage_count,
                "threshold": int(knob("package.reuse_threshold")),
            },
        )
    return pcp


async def list_pcps(session, product_space_id: str) -> list[PcpWeightTable]:
    return list(
        (
            await session.scalars(
                select(PcpWeightTable)
                .where(PcpWeightTable.product_space_id == product_space_id)
                .order_by(PcpWeightTable.platform)
            )
        ).all()
    )


# ---------- Q37 动态信号事件 ----------


async def list_events(
    session, platform: str | None = None, status: str | None = "active"
) -> list[PlatformDynamicEvent]:
    stmt = select(PlatformDynamicEvent).order_by(
        PlatformDynamicEvent.effective_start.desc()
    )
    if platform is not None:
        stmt = stmt.where(PlatformDynamicEvent.platform == platform)
    if status is not None:
        stmt = stmt.where(PlatformDynamicEvent.status == status)
    return list((await session.scalars(stmt)).all())


async def create_event(session, body, actor) -> PlatformDynamicEvent:
    """Q37 运营手工登记平台动态事件；登记后由每周重算与 match advisory 消费。"""
    _require_ops(actor)
    item = body.item
    if item.effective_end is not None and item.effective_end < item.effective_start:
        raise EventPeriodInvalid("effective_end < effective_start")
    ev = PlatformDynamicEvent(
        platform=item.platform,
        slot_id=item.slot_id,
        event_type=item.event_type,
        severity=item.severity,
        effective_start=item.effective_start,
        effective_end=item.effective_end,
        note=item.note,
        created_by=actor.id,
    )
    session.add(ev)
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="signal.event.created",
        entity_type="platform_dynamic_event",
        entity_id=ev.event_id,
        detail={
            "platform": ev.platform,
            "slot_id": ev.slot_id,
            "event_type": ev.event_type,
            "severity": ev.severity,
        },
    )
    return ev


async def update_event(session, event_id: str, body, actor) -> PlatformDynamicEvent:
    _require_ops(actor)
    ev = await session.get(PlatformDynamicEvent, event_id)
    if ev is None:
        raise EventNotFound(event_id)
    item = body.item
    if item.effective_end is not None and item.effective_end < item.effective_start:
        raise EventPeriodInvalid("effective_end < effective_start")
    ev.platform = item.platform
    ev.slot_id = item.slot_id
    ev.event_type = item.event_type
    ev.severity = item.severity
    ev.effective_start = item.effective_start
    ev.effective_end = item.effective_end
    ev.note = item.note
    ev.updated_at = _now()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="signal.event.updated",
        entity_type="platform_dynamic_event",
        entity_id=event_id,
        detail={"event_type": ev.event_type, "severity": ev.severity},
    )
    return ev


async def archive_event(session, event_id: str, actor) -> None:
    _require_ops(actor)
    ev = await session.get(PlatformDynamicEvent, event_id)
    if ev is None:
        raise EventNotFound(event_id)
    ev.status = "archived"
    ev.updated_at = _now()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="signal.event.archived",
        entity_type="platform_dynamic_event",
        entity_id=event_id,
        detail={"event_type": ev.event_type, "severity": ev.severity},
    )


async def active_events_for(
    session, platform: str, slot_id: str | None = None
) -> list[PlatformDynamicEvent]:
    """当前生效的事件（advisory 消费方：平台规则 match 时回带，不改变规则判定）。"""
    now = _now()
    stmt = select(PlatformDynamicEvent).where(
        PlatformDynamicEvent.platform == platform,
        PlatformDynamicEvent.status == "active",
        PlatformDynamicEvent.effective_start <= now,
        (PlatformDynamicEvent.effective_end.is_(None))
        | (PlatformDynamicEvent.effective_end >= now),
    ).order_by(PlatformDynamicEvent.effective_start.desc())
    if slot_id is not None:
        stmt = stmt.where(
            (PlatformDynamicEvent.slot_id == slot_id)
            | (PlatformDynamicEvent.slot_id.is_(None))
        )
    return list((await session.scalars(stmt)).all())


# ---------- Q296 甲：PLATFORM-ADAPTER 只读预览口 ----------


async def platform_adapter_preview(
    session,
    *,
    pws_snapshot_id: str,
    platform: str,
    slot_type: str,
    slot_id: str | None = None,
    country: str | None = None,
    previewed_by: str,
) -> dict:
    """PLATFORM-ADAPTER 只读预览口（design-v2-platform-adapter-business §3.1，Q296 甲）。

    组 Prompt v0.1 的三料（$pws←PWS 快照／$platform_rules←Q36 四层命中／
    $dynamic_events←生效事件）→ 经模型网关按 ai_scene_routes 调 PLATFORM-ADAPTER
    场景（V1 路由 synthetic，零写入；切真模型属丙批，届时预算/成本沿网关既有口径）→
    四态建议直接回带。**零落库、零审计、不改任何判定、不产候选、不触 final_id**
    （PT 约束 4/6；与 Q249 FCW 预检只读口同型）。无 frozen PWS 走协议内的缺失
    形状（PT 约束 7），与「快照不存在」（PwsSnapshotNotFound→404）区分。
    """
    pws = await session.get(PwsSnapshot, pws_snapshot_id)
    if pws is None:
        raise PwsSnapshotNotFound(pws_snapshot_id)
    matched = await _match_rule_rows(
        session, platform=platform, slot_type=slot_type, slot_id=slot_id, country=country
    )
    events = await active_events_for(session, platform, slot_id=slot_id)
    event_views = [
        {
            "event_id": e.event_id,
            "platform": e.platform,
            "slot_id": e.slot_id,
            "event_type": e.event_type,
            "severity": e.severity,
            "effective_start": e.effective_start.isoformat(),
            "effective_end": e.effective_end.isoformat() if e.effective_end else None,
            "note": e.note,
            "status": e.status,
        }
        for e in events
    ]
    variables = {
        "pws": {
            "pws_id": pws.pws_id,
            "version": pws.version,
            "product_space_id": pws.product_space_id,
            "frozen": pws.status == "frozen",
        },
        "platform_rules": [
            {
                "rule_id": r.rule_id,
                "effect": r.effect,
                "selector_level": r.selector_level,
                "country": r.country,
            }
            for r in matched
        ],
        "dynamic_events": event_views,
    }
    invocation = await gateway.invoke(session, SCENE_PLATFORM_ADAPTER, variables)
    result = json.loads(invocation.text)
    if "decision" not in result:
        # synthetic 无 frozen PWS 分支 V1 只返两键（Q246）；预览口是第一个真实消费方，
        # 按 Prompt v0.1 五键契约在消费方归一（Q293 §2.5 形状缺口，docs/05 登记）。
        result = {**result, "decision": None, "refs": [], "gate": None}
    return {
        "pws": variables["pws"],
        "input": {
            "platform": platform,
            "slot_type": slot_type,
            "slot_id": slot_id,
            "country": country,
        },
        "platform_rules": {
            "effect": pa_rules.resolve_effect(matched),
            "matched_rule_ids": [r.rule_id for r in matched],
        },
        "dynamic_events": event_views,
        "adapter": result,
        "previewed_by": previewed_by,
    }


# ---------- Q300 PLATFORM-ADAPTER 候选 + HumanGate（advisory，不产 final_id）----------

ADAPTER_SOURCE_SYNTHETIC = "synthetic"


async def list_adapter_candidates(
    session, status: str | None = None
) -> list[PlatformAdapterCandidate]:
    stmt = select(PlatformAdapterCandidate).order_by(
        PlatformAdapterCandidate.created_at.desc()
    )
    if status is not None:
        stmt = stmt.where(PlatformAdapterCandidate.status == status)
    return list((await session.scalars(stmt)).all())


async def create_adapter_candidate(session, body, actor) -> PlatformAdapterCandidate:
    """运营显式触发：复用 Q296 预览口的组料 + synthetic 网关，把四态建议落成
    pending 候选（design-v2-platform-adapter §3.2 乙，PT 约束 1-7）。

    只登记建议，不改任何判定；同 (pws, platform, slot_type, slot_id) 仅一条
    pending（partial unique，service 先查给 409）。
    """
    _require_ops(actor)
    pws = await session.get(PwsSnapshot, body.pws_snapshot_id)
    if pws is None:
        raise PwsSnapshotNotFound(body.pws_snapshot_id)
    coalesced_slot_id = body.slot_id or ""
    existing = (
        await session.scalars(
            select(PlatformAdapterCandidate).where(
                PlatformAdapterCandidate.pws_snapshot_id == body.pws_snapshot_id,
                PlatformAdapterCandidate.platform == body.platform,
                PlatformAdapterCandidate.slot_type == body.slot_type,
                PlatformAdapterCandidate.coalesce_slot_id == coalesced_slot_id,
                PlatformAdapterCandidate.status == CAND_PENDING,
            )
        )
    ).first()
    if existing is not None:
        raise PendingCandidateExists(existing.candidate_id)

    preview = await platform_adapter_preview(
        session,
        pws_snapshot_id=body.pws_snapshot_id,
        platform=body.platform,
        slot_type=body.slot_type,
        slot_id=body.slot_id,
        country=body.country,
        previewed_by=actor.id,
    )
    adapter = preview["adapter"]
    cand = PlatformAdapterCandidate(
        pws_snapshot_id=body.pws_snapshot_id,
        platform=body.platform,
        slot_type=body.slot_type,
        slot_id=body.slot_id,
        coalesce_slot_id=coalesced_slot_id,
        country=body.country,
        source=ADAPTER_SOURCE_SYNTHETIC,
        decision=adapter.get("decision"),
        reason=adapter.get("reason") or "",
        refs=list(adapter.get("refs") or []),
        missing=bool(adapter.get("missing")),
        status=CAND_PENDING,
        created_by=actor.id,
    )
    session.add(cand)
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="platform_adapter.candidate_created",
        entity_type="platform_adapter_candidate",
        entity_id=cand.candidate_id,
        detail={
            "pws_snapshot_id": body.pws_snapshot_id,
            "platform": body.platform,
            "decision": cand.decision,
            "missing": cand.missing,
            "source": ADAPTER_SOURCE_SYNTHETIC,
        },
    )
    return cand


async def approve_adapter_candidate(
    session, candidate_id: str, actor
) -> PlatformAdapterCandidate:
    """PT 约束 6：approve 只解除 pending 并留痕——不放行到 final_id、不改平台
    规则/发布位、不触发任何下游（唯一出口仍是段11 publishFCW）。"""
    _require_ops(actor)
    cand = await session.get(PlatformAdapterCandidate, candidate_id)
    if cand is None or cand.status != CAND_PENDING:
        raise AdapterCandidateNotFound(candidate_id)
    cand.status = CAND_APPROVED
    cand.approved_by = actor.id
    cand.approved_at = _now()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="platform_adapter.approved",
        entity_type="platform_adapter_candidate",
        entity_id=candidate_id,
        detail={"decision": cand.decision, "advisory_only": True},
    )
    return cand


async def reject_adapter_candidate(
    session, candidate_id: str, reason: str, actor
) -> PlatformAdapterCandidate:
    _require_ops(actor)
    if not reason or not reason.strip():
        raise AdapterDecisionRequired("reject reason is required")
    cand = await session.get(PlatformAdapterCandidate, candidate_id)
    if cand is None or cand.status != CAND_PENDING:
        raise AdapterCandidateNotFound(candidate_id)
    cand.status = CAND_REJECTED
    cand.rejected_reason = reason
    cand.rejected_by = actor.id
    cand.rejected_at = _now()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="platform_adapter.rejected",
        entity_type="platform_adapter_candidate",
        entity_id=candidate_id,
        detail={"reason": reason},
    )
    return cand


# ---------- Q41/Q42 PCP 重算候选 HumanGate ----------


async def list_candidates(
    session, status: str | None = None
) -> list[PcpRecalcCandidate]:
    stmt = select(PcpRecalcCandidate).order_by(
        PcpRecalcCandidate.created_at.desc()
    )
    if status is not None:
        stmt = stmt.where(PcpRecalcCandidate.status == status)
    return list((await session.scalars(stmt)).all())


async def create_candidate(session, body, actor) -> PcpRecalcCandidate:
    """Q41 候选提交（V1 仅 manual；AI 生成器随 V2）。

    Q40 统一校验器强制 Σ≤1.0；Q42 单项变化 ≤ platform.recalc_step（默认 ±0.05），
    超出即走人工直编通道（既有 PUT /api/pcp/{pcp_id}，无幅度限制）；同 PCP 同刻
    仅一条 pending（partial unique index）。
    """
    _require_ops(actor)
    pcp = await session.get(PcpWeightTable, body.pcp_id)
    if pcp is None:
        raise PcpNotFound(body.pcp_id)
    if pcp.status != "active":
        raise PcpNotFound(body.pcp_id)
    violations = pa_rules.validate_weights_17(body.proposed_weights)
    if violations:
        raise ValidationFailed(violations)
    step = float(knob(RECALC_STEP_KEY))
    changes = []
    for key, new in body.proposed_weights.items():
        old = pcp.weights.get(key)
        if old is None:
            continue
        if abs(float(new) - float(old)) > step + 1e-9:
            raise RecalcStepExceeded(
                f"{key}: |{old}->{new}| > {step} (use manual direct-edit PUT)"
            )
        if abs(float(new) - float(old)) > 1e-9:
            changes.append(
                {
                    "field": key,
                    "old": old,
                    "new": new,
                    "reason": "recalc candidate (manual)",
                }
            )
    pending = (
        await session.scalars(
            select(PcpRecalcCandidate).where(
                PcpRecalcCandidate.pcp_id == body.pcp_id,
                PcpRecalcCandidate.status == CAND_PENDING,
            )
        )
    ).first()
    if pending is not None:
        raise PendingCandidateExists(pending.candidate_id)
    cand = PcpRecalcCandidate(
        pcp_id=pcp.pcp_id,
        tenant_id=pcp.tenant_id,
        product_space_id=pcp.product_space_id,
        platform=pcp.platform,
        source=SOURCE_MANUAL,
        proposed_weights=dict(body.proposed_weights),
        change_list=changes,
        created_by=actor.id,
    )
    session.add(cand)
    await session.flush()
    await append_audit(
        session,
        tenant_id=pcp.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pcp.recalc_candidate_created",
        entity_type="pcp_recalc_candidate",
        entity_id=cand.candidate_id,
        detail={
            "pcp_id": pcp.pcp_id,
            "source": SOURCE_MANUAL,
            "changes": len(changes),
        },
    )
    return cand


async def approve_candidate(session, candidate_id: str, actor) -> PcpRecalcCandidate:
    """Q41 HumanGate 批准生效：写回 pcp_weight_tables + 清 template_code（Q42
    人工直编语义）+ before/after 审计。"""
    _require_ops(actor)
    cand = await session.get(PcpRecalcCandidate, candidate_id)
    if cand is None:
        raise EventNotFound(candidate_id)
    if cand.status != CAND_PENDING:
        raise EventNotFound(candidate_id)
    pcp = await session.get(PcpWeightTable, cand.pcp_id)
    if pcp is None or pcp.status != "active":
        raise PcpNotFound(cand.pcp_id)
    before = dict(pcp.weights)
    pcp.weights = dict(cand.proposed_weights)
    pcp.template_code = None
    pcp.updated_at = _now()
    cand.status = CAND_APPROVED
    cand.approved_by = actor.id
    cand.approved_at = _now()
    await append_audit(
        session,
        tenant_id=pcp.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pcp.recalc_applied",
        entity_type="pcp_weight_table",
        entity_id=pcp.pcp_id,
        detail={
            "candidate_id": cand.candidate_id,
            "before": before,
            "after": dict(pcp.weights),
            "change_list": cand.change_list,
        },
    )
    await append_audit(
        session,
        tenant_id=pcp.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pcp.recalc_approved",
        entity_type="pcp_recalc_candidate",
        entity_id=cand.candidate_id,
        detail={"pcp_id": pcp.pcp_id},
    )
    return cand


async def reject_candidate(
    session, candidate_id: str, reason: str, actor
) -> PcpRecalcCandidate:
    _require_ops(actor)
    cand = await session.get(PcpRecalcCandidate, candidate_id)
    if cand is None:
        raise EventNotFound(candidate_id)
    if cand.status != CAND_PENDING:
        raise EventNotFound(candidate_id)
    cand.status = CAND_REJECTED
    cand.rejected_reason = reason
    cand.rejected_by = actor.id
    cand.rejected_at = _now()
    await append_audit(
        session,
        tenant_id=cand.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pcp.recalc_rejected",
        entity_type="pcp_recalc_candidate",
        entity_id=candidate_id,
        detail={"reason": reason},
    )
    return cand


# ---------- Q294：每周重算提醒（PT-PCP-V1.5「动态信号每周更新触发重算」V2 第一切片）----------


def weekly_recalc_anchor(
    now: datetime, weekday: int, hour: int, tz_offset_hours: int
) -> datetime:
    """本地周节奏 ``(weekday, hour)`` 对应的**最近一次已到点锚点**（返回 UTC）。

    ``weekday`` 以周一=0（``datetime.weekday()`` 同口径）。钟点未到则退回上一周期，
    保证同一周期内任意 tick 得到同一个锚点（周节奏只认锚点、不认 tick 次数）。

    Q294 甲案：固定 UTC 偏移口径。中国自 1991 年起无夏令时，固定偏移与 Asia/Shanghai
    恒等；镜像 ``python:3.12-slim`` 无系统 tz 数据库，用具名时区会 ZoneInfoNotFound，
    故刻意不引 tzdata 依赖（带 DST 的时区须另裁）。
    """
    local = now.astimezone(timezone(timedelta(hours=tz_offset_hours)))
    anchor = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    anchor -= timedelta(days=(local.weekday() - weekday) % 7)
    if anchor > local:
        anchor -= CYCLE
    return anchor.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    """读回的日期时间归一为 UTC。

    PG timestamptz 读回即 aware；SQLite 读回落掉偏移为 naive（存储串不含 offset），
    而 server_default=now() 两侧都记 UTC ⇒ naive 一律按 UTC 解释（Q294）。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _pending_candidate_exists(session, pcp_id: str) -> bool:
    """该 PCP 是否已有在途（pending）重算候选——有则运营已在处理，不再打扰。"""
    return (
        await session.scalar(
            select(PcpRecalcCandidate.candidate_id)
            .where(
                PcpRecalcCandidate.pcp_id == pcp_id,
                PcpRecalcCandidate.status == CAND_PENDING,
            )
            .limit(1)
        )
        is not None
    )


async def scan_weekly_recalc_reminders(session, now: datetime) -> int:
    """Q294：为一周内「新生效动态事件」对应的 PCP 开/续一条重算提醒待办。

    触发机制 3.1 甲（SweepScheduler 登记作业，门控见 config）+ 产出 3.2 甲（只提醒），
    闭合 docs/01 段8 PT-PCP-V1.5「动态信号每周更新触发重算」的**产品内节奏**缺口：

    1. 只扫**本周期窗口内新生效**的 active 事件（上一锚点之后、本锚点及之前）；
       无新事件的周直接跳过（Q294 待裁点 3 推荐口径）。
    2. 事件命中平台的每个 active PCP：已有 pending 候选的不打扰（人工 Gate 红线：
       提醒不得与在途裁决叠加）。
    3. 开/续一条 ``pcp_weekly_recalc`` OpsTodo（assignee=operations）：无开放待办则新建，
       有开放/escalated 待办则续期（刷新命中事件与 due_at，不重复开条）；本周期内已提醒过
       （含已 resolved）的不再重复。
    4. **不生成权重、不建候选、不写回 pcp_weight_tables**——事件→17 字段权重的映射规则
       原文未给出（禁臆造），运营据提醒走既有 manual 候选 → 人工 Gate。

    不自行提交（提交边界由统一 sweep runner 负责）；单轮影响行数（新建+续期）为返回值。
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    weekday = int(knob(WEEKDAY_KEY))
    hour = int(knob(HOUR_KEY))
    tz_offset = int(knob(TZ_OFFSET_KEY))
    due_days = int(knob(TODO_DUE_DAYS_KEY))
    anchor = weekly_recalc_anchor(now, weekday, hour, tz_offset)
    cycle_start = anchor - CYCLE

    events = list(
        (
            await session.scalars(
                select(PlatformDynamicEvent)
                .where(
                    PlatformDynamicEvent.status == "active",
                    PlatformDynamicEvent.effective_start > cycle_start,
                    PlatformDynamicEvent.effective_start <= anchor,
                )
                .order_by(
                    PlatformDynamicEvent.platform, PlatformDynamicEvent.effective_start
                )
            )
        ).all()
    )
    if not events:
        return 0

    hits_by_platform: dict[str, list[PlatformDynamicEvent]] = {}
    for ev in events:
        hits_by_platform.setdefault(ev.platform, []).append(ev)

    acted = 0
    for platform in sorted(hits_by_platform):
        hits = hits_by_platform[platform]
        event_ids = [ev.event_id for ev in hits]
        pcps = list(
            (
                await session.scalars(
                    select(PcpWeightTable)
                    .where(
                        PcpWeightTable.platform == platform,
                        PcpWeightTable.status == "active",
                    )
                    .order_by(PcpWeightTable.pcp_id)
                )
            ).all()
        )
        for pcp in pcps:
            if await _pending_candidate_exists(session, pcp.pcp_id):
                continue
            open_todo = await session.scalar(
                select(OpsTodo)
                .where(
                    OpsTodo.todo_type == TODO_TYPE_PCP_WEEKLY_RECALC,
                    OpsTodo.entity_type == ENTITY_TYPE_PCP,
                    OpsTodo.entity_id == pcp.pcp_id,
                    OpsTodo.status.in_(["open", "escalated"]),
                )
                .order_by(OpsTodo.created_at.desc())
            )
            if open_todo is None:
                last_at = await session.scalar(
                    select(func.max(OpsTodo.created_at)).where(
                        OpsTodo.todo_type == TODO_TYPE_PCP_WEEKLY_RECALC,
                        OpsTodo.entity_type == ENTITY_TYPE_PCP,
                        OpsTodo.entity_id == pcp.pcp_id,
                    )
                )
                if last_at is not None and _as_utc(last_at) >= cycle_start:
                    # 本周期已提醒过（无论是否已被 resolved），不重复打扰。
                    continue
            detail = {
                "platform": platform,
                "product_space_id": pcp.product_space_id,
                "pcp_id": pcp.pcp_id,
                "event_ids": event_ids,
                "event_count": len(event_ids),
                "cycle_start": cycle_start.isoformat(),
                "anchor": anchor.isoformat(),
                "next_step": "人工提交 recalc 候选并过 Gate（不自动改权重）",
            }
            if open_todo is None:
                todo = OpsTodo(
                    tenant_id=pcp.tenant_id,
                    todo_type=TODO_TYPE_PCP_WEEKLY_RECALC,
                    entity_type=ENTITY_TYPE_PCP,
                    entity_id=pcp.pcp_id,
                    assignee_role=ROLE_OPERATIONS,
                    detail={**detail, "renewed": False},
                    due_at=now + timedelta(days=due_days),
                )
                session.add(todo)
                await session.flush()
            else:
                # 续期：跨周期仍未处理 ⇒ 刷新命中事件并顺延截止，不另开新条。
                open_todo.detail = {**detail, "renewed": True}
                open_todo.due_at = now + timedelta(days=due_days)
                open_todo.assignee_role = ROLE_OPERATIONS
            await append_audit(
                session,
                tenant_id=pcp.tenant_id,
                actor_id=None,
                actor_roles=None,
                action=RECALC_TODO_ACTION,
                entity_type=ENTITY_TYPE_PCP,
                entity_id=pcp.pcp_id,
                detail={**detail, "renewed": open_todo is not None},
            )
            acted += 1
    return acted
