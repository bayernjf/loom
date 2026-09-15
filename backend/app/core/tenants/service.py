"""租户注册表生命周期服务（Q95）。

开通（默认 trial/trial；选付费档→active）、改套餐（续费口径，不动 status）、
暂停/恢复（paused→active）、段1 准入闸（未知租户拒登、暂停租户拒登）。
团队/账号管理随真实认证 V2（Actor 无租户归属，本切片不做成员绑定）。
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.rbac import PLATFORM_ADMIN, require_any_role
from app.core.tenants.models import (
    PLANS,
    TRIAL_MONTHLY_TOKEN_QUOTA,
    Tenant,
)
from app.product.product_intake.models import (
    ProductIntakeApplication,
    ProductSpace,
)


class TenantNotFound(Exception):
    pass


class TenantExists(Exception):
    pass


class TenantPaused(Exception):
    pass


class InvalidPlan(Exception):
    pass


class IllegalTenantLifecycle(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


async def provision_tenant(
    session: AsyncSession,
    *,
    tenant_id: str,
    name: str | None,
    plan: str,
    actor,
) -> Tenant:
    require_any_role(actor, PLATFORM_ADMIN)
    if plan not in PLANS:
        raise InvalidPlan(f"unknown plan {plan!r}; valid plans: {', '.join(PLANS)}")
    if await session.get(Tenant, tenant_id) is not None:
        raise TenantExists(tenant_id)

    # 开通即试用 → status=trial；选付费档开通 → active（Q95 接缝②）。
    status = "trial" if plan == "trial" else "active"
    quota = TRIAL_MONTHLY_TOKEN_QUOTA if plan == "trial" else None
    tenant = Tenant(
        tenant_id=tenant_id,
        name=name,
        plan=plan,
        status=status,
        monthly_token_quota=quota,
        detail={},
        created_by=actor.id,
    )
    session.add(tenant)
    await session.flush()
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="tenant.provisioned",
        entity_type="tenant",
        entity_id=tenant_id,
        detail={"name": name, "plan": plan, "status": status},
    )
    return tenant


async def list_tenants(session: AsyncSession) -> list[Tenant]:
    return list(
        (
            await session.scalars(select(Tenant).order_by(Tenant.created_at, Tenant.tenant_id))
        ).all()
    )


async def get_tenant(session: AsyncSession, tenant_id: str) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise TenantNotFound(tenant_id)
    return tenant


async def onboarding_progress(session: AsyncSession, tenant_id: str) -> dict:
    """派生 Onboarding 进度：注册/套餐来自注册表本身；建模/上线看业务锚点存在与计数。

    第一产品建模→AI 拆解→上线 复用既有 intake→PS→链，无独立引导状态机（Q95 接缝③）。
    """
    intake_count = await session.scalar(
        select(func.count())
        .select_from(ProductIntakeApplication)
        .where(ProductIntakeApplication.tenant_id == tenant_id)
    )
    space_count = await session.scalar(
        select(func.count())
        .select_from(ProductSpace)
        .where(ProductSpace.tenant_id == tenant_id)
    )
    return {
        "intakes": int(intake_count or 0),
        "product_spaces": int(space_count or 0),
        "first_modeling_started": bool(space_count),
    }


async def change_plan(
    session: AsyncSession, *, tenant_id: str, plan: str, actor
) -> Tenant:
    """续费/改套餐：只动 plan，status 保持不变（Q95 接缝②）。"""
    require_any_role(actor, PLATFORM_ADMIN)
    if plan not in PLANS:
        raise InvalidPlan(f"unknown plan {plan!r}; valid plans: {', '.join(PLANS)}")
    tenant = await get_tenant(session, tenant_id)
    old_plan = tenant.plan
    tenant.plan = plan
    # 只有试用档额度有原文数值；切到付费档置空（各档额度【原文未给出，待补】）。
    tenant.monthly_token_quota = (
        TRIAL_MONTHLY_TOKEN_QUOTA if plan == "trial" else None
    )
    tenant.plan_changed_by = actor.id
    tenant.plan_changed_at = _now()
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="tenant.plan_changed",
        entity_type="tenant",
        entity_id=tenant_id,
        detail={"from": old_plan, "to": plan, "status": tenant.status},
    )
    return tenant


async def pause_tenant(session: AsyncSession, *, tenant_id: str, actor) -> Tenant:
    require_any_role(actor, PLATFORM_ADMIN)
    tenant = await get_tenant(session, tenant_id)
    if tenant.status == "paused":
        raise IllegalTenantLifecycle("tenant is already paused")
    old_status = tenant.status
    tenant.status = "paused"
    tenant.paused_by = actor.id
    tenant.paused_at = _now()
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="tenant.paused",
        entity_type="tenant",
        entity_id=tenant_id,
        detail={"from": old_status},
    )
    return tenant


async def resume_tenant(session: AsyncSession, *, tenant_id: str, actor) -> Tenant:
    require_any_role(actor, PLATFORM_ADMIN)
    tenant = await get_tenant(session, tenant_id)
    if tenant.status != "paused":
        raise IllegalTenantLifecycle(f"tenant is not paused (status={tenant.status})")
    tenant.status = "active"
    tenant.paused_by = None
    tenant.paused_at = None
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="tenant.resumed",
        entity_type="tenant",
        entity_id=tenant_id,
    )
    return tenant


async def assert_intake_admitted(session: AsyncSession, tenant_id: str) -> Tenant:
    """段1 准入闸（应用层；不设硬外键，存量业务表不动，Q95 接缝①/④）。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise TenantNotFound(tenant_id)
    if tenant.status == "paused":
        raise TenantPaused(tenant_id)
    return tenant
