"""段9 三包配置实例服务（V1 静态切片，08 M11）。

V1 为运营手工配置实例（Q45 三元组配一份）；WF-07 AI 选料、Q43 字典选料约束、
满 20 次/PCP 更新触发重配均随 V2（08 P2）。
"""

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.audit import append_audit
from app.decision.layer_strategy.models import KIND_PAYLOAD_KEYS, PACKAGE_KINDS, Package
from app.product.condition.models import ContentGoal
from app.product.product_intake.models import ProductSpace

ROLE_OPERATIONS = "operations"


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
