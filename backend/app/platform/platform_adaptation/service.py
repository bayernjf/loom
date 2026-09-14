"""段7/8 静态底表服务（08 M11）：发布位/规则/默认值/fit 权重/PCP。

角色口径：后台档案 CRUD = operations（Q35）；所有写操作 writeAudit。
"""

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.audit import append_audit
from app.platform.platform_adaptation import pa_rules
from app.platform.platform_adaptation.models import (
    GoalFitWeight,
    PcpTemplate,
    PcpWeightTable,
    PlatformRule,
    PublishSlot,
    SlotTypeDefault,
)
from app.product.condition.models import ContentGoal
from app.product.product_intake.models import ProductSpace

PLATFORM_TENANT = "_platform"
ROLE_OPERATIONS = "operations"


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
    for key, value in body.item.model_dump().items():
        setattr(slot, key, value)
    slot.updated_at = _now()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="slot.update",
        entity_type="publish_slot",
        entity_id=slot_id,
        detail={"code": slot.code},
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
    """
    slot = await session.get(PublishSlot, slot_id)
    if slot is None:
        raise SlotNotFound(slot_id)
    row = await session.get(GoalFitWeight, goal)
    if row is None:
        return {"slot_id": slot_id, "goal": goal, "fit_score": None, "incomplete": True}
    return {
        "slot_id": slot_id,
        "goal": goal,
        "fit_score": pa_rules.compute_fit_score(slot, row.weights),
        "incomplete": False,
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
        detail={"weights": body.weights},
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


async def match_rules(
    session,
    *,
    platform: str,
    slot_type: str,
    slot_id: str | None = None,
    country: str | None = None,
) -> dict:
    """按格子命中规则并给出 Q36 裁决（供段7 适配与调试查看）。"""
    rows = list(
        (
            await session.scalars(
                select(PlatformRule).where(PlatformRule.status == "active")
            )
        ).all()
    )
    matched = [
        r
        for r in rows
        if (r.platform is None or r.platform == platform)
        and (r.slot_type is None or r.slot_type == slot_type)
        and (r.slot_id is None or r.slot_id == slot_id)
        and (r.country is None or r.country == country)
    ]
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
