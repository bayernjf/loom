"""段9 三包配置实例服务（V1 静态切片，08 M11）+ Q262 layerSpaces 通用底座（Q46）。

V1 为运营手工配置实例（Q45 三元组配一份）；WF-07 AI 选料、Q43 字典选料约束、
满 20 次/PCP 更新触发重配均随 V2（08 P2）。
Q262：layerSpaces 四层（04 §2.16）+ 原子池（docs/10 §2.5）CRUD——Q46 权限
单列（写=platform_admin）、变更前影响面显示（活跃配方=packages active 引用，
工程口径【实现补】）、Gate 确认、审计。
"""

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.audit import append_audit
from app.decision.layer_strategy.models import (
    ITEM_ARCHIVED,
    ITEM_WRITABLE_STATUSES,
    KIND_PAYLOAD_KEYS,
    LAYER_CODES,
    PACKAGE_KINDS,
    LayerSpace,
    LayerSpaceItem,
    Package,
)
from app.product.condition.models import ContentGoal
from app.product.product_intake.models import ProductSpace

ROLE_OPERATIONS = "operations"
ROLE_PLATFORM_ADMIN = "platform_admin"


class RoleNotAllowed(Exception):
    pass


class ValidationFailed(Exception):
    def __init__(self, violations: list[str]):
        super().__init__(str(violations))
        self.violations = violations


class PsNotFound(Exception):
    pass


class GoalNotFound(Exception):
    pass


class PackageNotFound(Exception):
    pass


class LayerNotFound(Exception):
    pass


class LayerItemNotFound(Exception):
    pass


class LayerItemExists(Exception):
    pass


class ImpactRequiresConfirmation(Exception):
    def __init__(self, refs: int):
        super().__init__(f"active packages reference this item: {refs}")
        self.refs = refs


class PackageExists(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _require_ops(actor) -> None:
    if ROLE_OPERATIONS not in actor.roles:
        raise RoleNotAllowed("requires operations role")


def _validate_payload(kind: str, payload: dict) -> None:
    keys = KIND_PAYLOAD_KEYS[kind]
    missing = [k for k in keys if k not in payload]
    unknown = sorted(set(payload) - set(keys))
    violations = []
    if missing:
        violations.append(f"missing_payload_keys:{','.join(missing)}")
    if unknown:
        violations.append(f"unknown_payload_keys:{','.join(unknown)}")
    if violations:
        raise ValidationFailed(violations)


async def create_package(session, product_space_id: str, body, actor) -> Package:
    _require_ops(actor)
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise PsNotFound(product_space_id)
    item = body.item
    if item.kind not in PACKAGE_KINDS:
        raise ValidationFailed([f"unknown_kind:{item.kind}"])
    goal = await session.get(ContentGoal, item.goal)
    if goal is None or goal.status != "active":
        raise GoalNotFound(item.goal)
    _validate_payload(item.kind, item.payload)
    existing = (
        await session.scalars(
            select(Package).where(
                Package.product_space_id == product_space_id,
                Package.platform == item.platform,
                Package.goal == item.goal,
                Package.kind == item.kind,
                Package.status == "active",
            )
        )
    ).first()
    if existing is not None:
        # Q45：（产品×平台×目的）三元组配一份。
        raise PackageExists(
            f"{product_space_id}/{item.platform}/{item.goal}/{item.kind}"
        )
    package = Package(
        kind=item.kind,
        tenant_id=ps.tenant_id,
        product_space_id=product_space_id,
        platform=item.platform,
        goal=item.goal,
        payload=item.payload,
        conf=item.conf,
        created_by=actor.id,
    )
    session.add(package)
    await session.flush()
    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="package.create",
        entity_type="package",
        entity_id=package.package_id,
        detail={"kind": item.kind, "platform": item.platform, "goal": item.goal},
    )
    return package


async def update_package(session, package_id: str, body, actor) -> Package:
    _require_ops(actor)
    package = await session.get(Package, package_id)
    if package is None:
        raise PackageNotFound(package_id)
    _validate_payload(package.kind, body.payload)
    package.payload = body.payload
    package.conf = body.conf
    package.updated_at = _now()
    await append_audit(
        session,
        tenant_id=package.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="package.update",
        entity_type="package",
        entity_id=package_id,
        detail={"kind": package.kind},
    )
    return package


async def archive_package(session, package_id: str, actor) -> None:
    _require_ops(actor)
    package = await session.get(Package, package_id)
    if package is None:
        raise PackageNotFound(package_id)
    package.status = "archived"
    package.updated_at = _now()
    await append_audit(
        session,
        tenant_id=package.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="package.archive",
        entity_type="package",
        entity_id=package_id,
        detail={"kind": package.kind},
    )


async def list_packages(
    session,
    product_space_id: str,
    *,
    platform: str | None = None,
    goal: str | None = None,
    status: str | None = "active",
) -> list[Package]:
    stmt = select(Package).where(Package.product_space_id == product_space_id)
    if platform:
        stmt = stmt.where(Package.platform == platform)
    if goal:
        stmt = stmt.where(Package.goal == goal)
    if status:
        stmt = stmt.where(Package.status == status)
    return list((await session.scalars(stmt.order_by(Package.kind))).all())


# ---------------------------------------------------------------------------
# Q262 layerSpaces 通用底座（Q46）
# ---------------------------------------------------------------------------


def _require_platform_admin(actor) -> None:
    if ROLE_PLATFORM_ADMIN not in actor.roles:
        raise RoleNotAllowed("requires platform_admin role")


def _payload_mentions(payload: dict, name: str) -> bool:
    """活跃配方引用判定：payload 任一层级标量值 === name（工程口径，标【实现补】）。

    Q46「被 N 个活跃配方引用」的精确匹配规则原文未给——三包 payload 值取自
    layerSpaces 原子（01 line 1261），此处按值全等判定，每行最多计 1。
    """

    def walk(value) -> bool:
        if isinstance(value, dict):
            return any(walk(v) for v in value.values())
        if isinstance(value, list):
            return any(walk(v) for v in value)
        return value == name

    return walk(payload)


async def item_refs(session, item: LayerSpaceItem) -> int:
    """活跃配方（packages status=active）中引用该原子的行数（每行计 1）。"""

    rows = (
        await session.scalars(
            select(Package).where(Package.status == "active")
        )
    ).all()
    return sum(1 for p in rows if _payload_mentions(p.payload, item.name))


async def list_layer_spaces(session) -> list[LayerSpace]:
    return list(
        (
            await session.scalars(
                select(LayerSpace).order_by(LayerSpace.sort_order)
            )
        ).all()
    )


async def list_items(
    session,
    *,
    layer_id: str | None = None,
    dimension: str | None = None,
    status: str | None = None,
) -> list[LayerSpaceItem]:
    stmt = select(LayerSpaceItem).order_by(
        LayerSpaceItem.layer_id, LayerSpaceItem.dimension, LayerSpaceItem.name
    )
    if layer_id:
        stmt = stmt.where(LayerSpaceItem.layer_id == layer_id)
    if dimension:
        stmt = stmt.where(LayerSpaceItem.dimension == dimension)
    if status:
        stmt = stmt.where(LayerSpaceItem.status == status)
    return list((await session.scalars(stmt)).all())


async def get_item(session, item_id: str) -> LayerSpaceItem:
    item = await session.get(LayerSpaceItem, item_id)
    if item is None or item.status == ITEM_ARCHIVED:
        raise LayerItemNotFound(item_id)
    return item


async def create_item(session, body, actor) -> LayerSpaceItem:
    _require_platform_admin(actor)
    layer = await session.get(LayerSpace, body.layer_id)
    if layer is None:
        raise LayerNotFound(body.layer_id)
    if layer.code not in LAYER_CODES:
        raise LayerNotFound(body.layer_id)
    if body.dimension not in layer.dimensions:
        raise ValidationFailed(
            [f"unknown_dimension:{body.dimension}:not_in_layer:{layer.code}"]
        )
    if body.status not in ITEM_WRITABLE_STATUSES:
        raise ValidationFailed([f"invalid_status:{body.status}"])
    existing = (
        await session.scalars(
            select(LayerSpaceItem).where(
                LayerSpaceItem.layer_id == body.layer_id,
                LayerSpaceItem.dimension == body.dimension,
                LayerSpaceItem.name == body.name,
            )
        )
    ).first()
    if existing is not None and existing.status != ITEM_ARCHIVED:
        raise LayerItemExists(f"{body.layer_id}/{body.dimension}/{body.name}")
    if existing is not None and existing.status == ITEM_ARCHIVED:
        # 软归档后同键重建（字典先例）：复活同键行。
        existing.status = body.status
        existing.created_by = actor.id
        existing.updated_at = _now()
        item = existing
    else:
        item = LayerSpaceItem(
            layer_id=body.layer_id,
            dimension=body.dimension,
            name=body.name,
            status=body.status,
            created_by=actor.id,
        )
        session.add(item)
    await session.flush()
    await append_audit(
        session,
        tenant_id="_platform",
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="layer_space.item_create",
        entity_type="layer_space_item",
        entity_id=item.item_id,
        detail={"layer": layer.code, "dimension": body.dimension, "name": body.name},
    )
    return item


async def update_item(
    session, item_id: str, body, actor, *, refs: int | None = None
) -> LayerSpaceItem:
    _require_platform_admin(actor)
    item = await session.get(LayerSpaceItem, item_id)
    if item is None or item.status == ITEM_ARCHIVED:
        raise LayerItemNotFound(item_id)
    if refs is None:
        refs = await item_refs(session, item)
    changing_identity = body.name is not None and body.name != item.name
    if changing_identity and refs > 0 and not body.impact_confirmed:
        raise ImpactRequiresConfirmation(refs)
    if body.name is not None:
        item.name = body.name
    if body.status is not None:
        if body.status not in ITEM_WRITABLE_STATUSES:
            raise ValidationFailed([f"invalid_status:{body.status}"])
        item.status = body.status
    item.updated_at = _now()
    await append_audit(
        session,
        tenant_id="_platform",
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="layer_space.item_update",
        entity_type="layer_space_item",
        entity_id=item_id,
        detail={
            "name": body.name,
            "status": body.status,
            "refs": refs,
            "impact_confirmed": body.impact_confirmed,
        },
    )
    return item


async def archive_item(
    session, item_id: str, body, actor, *, refs: int | None = None
) -> None:
    _require_platform_admin(actor)
    item = await session.get(LayerSpaceItem, item_id)
    if item is None or item.status == ITEM_ARCHIVED:
        raise LayerItemNotFound(item_id)
    if refs is None:
        refs = await item_refs(session, item)
    if refs > 0 and not body.impact_confirmed:
        raise ImpactRequiresConfirmation(refs)
    item.status = ITEM_ARCHIVED
    item.updated_at = _now()
    await append_audit(
        session,
        tenant_id="_platform",
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="layer_space.item_archive",
        entity_type="layer_space_item",
        entity_id=item_id,
        detail={"refs": refs, "impact_confirmed": body.impact_confirmed},
    )
