from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.tenants.service import assert_intake_admitted
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import (
    G2Field,
    ProductIntakeApplication,
    ProductSpace,
)


class IntakeNotFound(Exception):
    pass


class MissingRequiredFields(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"missing required G2 common fields: {missing}")


async def _required_common_fids(session: AsyncSession) -> list[str]:
    """完整度闸门按 g2_fields 中 active 的 cat='common' 行动态判定（Q74：名单不硬编码）。"""
    rows = await session.scalars(
        select(G2Field.fid).where(G2Field.cat == "common", G2Field.status == "active")
    )
    return sorted(rows.all())


async def create_intake(
    session: AsyncSession, *, tenant_id: str, profile: dict, actor_id: str | None = None
) -> ProductIntakeApplication:
    # Q95 段1 准入：未知租户拒登、暂停租户拒登（应用层闸，不设硬外键）。
    await assert_intake_admitted(session, tenant_id)
    intake = ProductIntakeApplication(
        tenant_id=tenant_id,
        profile=dict(profile),
        status=sm.DRAFT,
        created_by=actor_id,
    )
    session.add(intake)
    await session.flush()
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_roles=None,
        action="intake.create",
        entity_type="product_intake_application",
        entity_id=intake.intake_id,
    )
    await session.commit()
    return intake


async def get_intake(session: AsyncSession, intake_id: str) -> ProductIntakeApplication:
    intake = await session.get(ProductIntakeApplication, intake_id)
    if intake is None:
        raise IntakeNotFound(intake_id)
    return intake


async def list_intakes(
    session: AsyncSession, *, tenant_id: str, limit: int, offset: int
) -> tuple[list[ProductIntakeApplication], int]:
    # Q98：按租户只读列表；读路径不触发 Q95 准入门，未知租户返回空列表。
    stmt = select(ProductIntakeApplication).where(
        ProductIntakeApplication.tenant_id == tenant_id
    )
    total = await session.scalar(
        select(func.count()).select_from(stmt.subquery())
    )
    rows = await session.scalars(
        stmt.order_by(ProductIntakeApplication.created_at.desc()).limit(limit).offset(offset)
    )
    return list(rows.all()), int(total or 0)


async def list_ops_intakes(
    session: AsyncSession, *, status: str | None, limit: int, offset: int
) -> tuple[list[ProductIntakeApplication], int]:
    # Q107：运营跨租户队列（与 Q98 租户内列表分离，RBAC 在路由层 operations|platform_admin）。
    stmt = select(ProductIntakeApplication)
    if status is not None:
        stmt = stmt.where(ProductIntakeApplication.status == status)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.scalars(
        stmt.order_by(ProductIntakeApplication.created_at.desc()).limit(limit).offset(offset)
    )
    return list(rows.all()), int(total or 0)


async def overview_intakes(
    session: AsyncSession, *, tenant_id: str
) -> tuple[int, dict[str, int]]:
    # Q99：工作台总览只读聚合；读路径不触发 Q95 准入门，未知租户返回零值。
    rows = await session.execute(
        select(ProductIntakeApplication.status, func.count())
        .where(ProductIntakeApplication.tenant_id == tenant_id)
        .group_by(ProductIntakeApplication.status)
    )
    by_status = {status: int(count) for status, count in rows.all()}
    return sum(by_status.values()), by_status


class ProfileNotEditable(Exception):
    pass


_EDITABLE_STATES = frozenset({sm.DRAFT, sm.PENDING_PARAMS, sm.NEED_MORE_INFO})


async def update_profile(
    session: AsyncSession,
    *,
    intake_id: str,
    profile_patch: dict,
    actor_id: str,
) -> ProductIntakeApplication:
    """草稿/补资料阶段补全字段；进入审核后资料不可改（快照纪律，Q74）。"""
    intake = await get_intake(session, intake_id)
    if intake.status not in _EDITABLE_STATES:
        raise ProfileNotEditable(f"profile is not editable in state {intake.status}")
    intake.profile = {**intake.profile, **profile_patch}
    await append_audit(
        session,
        tenant_id=intake.tenant_id,
        actor_id=actor_id,
        actor_roles=None,
        action="intake.profile_update",
        entity_type="product_intake_application",
        entity_id=intake.intake_id,
        detail={"fields": sorted(profile_patch.keys())},
    )
    await session.commit()
    return intake


async def apply_event(
    session: AsyncSession,
    *,
    intake_id: str,
    event: str,
    actor_id: str,
    actor_roles: list[str],
    category_pending_id: str | None = None,
) -> ProductIntakeApplication:
    intake = await get_intake(session, intake_id)

    if event == "submit":
        required = await _required_common_fids(session)
        missing = sm.missing_required_fields(intake.profile, required)
        if missing:
            raise MissingRequiredFields(missing)

    old_status = intake.status
    new_status = sm.transition(old_status, event, actor_roles)
    intake.status = new_status
    if event == "wf01_cold_start" and category_pending_id:
        intake.category_pending_id = category_pending_id

    space: ProductSpace | None = None
    if event == "start_modeling":
        # 已通过→建模中：生成 PS 并整体复制资料快照（Q74）。
        space = ProductSpace(
            tenant_id=intake.tenant_id,
            intake_id=intake.intake_id,
            lifecycle=sm.MODELING,
            profile_snapshot=dict(intake.profile),
        )
        session.add(space)

    await append_audit(
        session,
        tenant_id=intake.tenant_id,
        actor_id=actor_id,
        actor_roles=actor_roles,
        action=f"intake.{event}",
        entity_type="product_intake_application",
        entity_id=intake.intake_id,
        detail={"from": old_status, "to": new_status, "space_created": bool(space)},
    )
    await session.commit()
    return intake
