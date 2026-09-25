from datetime import UTC, datetime

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


class ProductSpaceNotCreated(Exception):
    """B3：产品空间尚未生成（start_modeling 之前无 target-languages 可设）。"""


class TargetLanguagesInvalid(Exception):
    """B3：目标语言含重复码或不在 active content_languages 清单内。"""


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


async def set_target_languages(
    session: AsyncSession,
    *,
    intake_id: str,
    tenant_id: str,
    languages: list[str],
    actor,
) -> ProductSpace:
    """B3/Q122：客户在段1 录入页设置产品目标语言（客户口径，无 OPERATIONS 闸）。

    与 Q119 operations ``PUT /api/product-spaces/{id}/target-languages`` 写同一列，
    但按 intake 维度定位产品空间，并额外校验语言码必须在 active content_languages
    清单内（运营代设入口维持原校验口径不变）；空列表 = 未声明 / 不收窄。
    Q200 #32：客户口必须显式声明 tenant_id，与产品空间归属不符统一 404。
    """
    # 惰性 import：content.languages 反向依赖 product_intake.models，避开模块加载环。
    from app.content.languages import list_languages

    ps = await session.scalar(
        select(ProductSpace).where(ProductSpace.intake_id == intake_id)
    )
    if ps is None or ps.tenant_id != tenant_id:
        raise ProductSpaceNotCreated(intake_id)

    codes = [c.strip() for c in (languages or []) if isinstance(c, str) and c.strip()]
    if len(set(codes)) != len(codes):
        raise TargetLanguagesInvalid("target languages must be unique")
    active_codes = {lang.code for lang in await list_languages(session)}
    unknown = sorted(set(codes) - active_codes)
    if unknown:
        raise TargetLanguagesInvalid(
            f"unknown/inactive language codes: {', '.join(unknown)}"
        )

    ps.target_languages = codes or None
    ps.updated_at = datetime.now(UTC)
    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="product_space.target_languages.set",
        entity_type="product_space",
        entity_id=ps.product_space_id,
        detail={"target_languages": ps.target_languages, "channel": "customer_intake"},
    )
    await session.commit()
    return ps
