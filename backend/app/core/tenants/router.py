"""租户管理端点（Q95；platform_admin 红线，09 D3.11）。

GET 管理面口径同 Q92 驾驶舱：actor 经 query（actor_id 必填→422、roles 不符→403）；
写端点 actor 在请求体，同 agent-keys 先例。价格仅展示用，不在此后端契约内。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.rbac import PLATFORM_ADMIN, PermissionDenied, require_any_role
from app.core.tenants import service
from app.core.tenants.schemas import (
    CustomerTenantView,
    TenantChangePlanRequest,
    TenantDetailView,
    TenantLifecycleRequest,
    TenantProvisionRequest,
    TenantView,
)

router = APIRouter(prefix="/api/admin/tenants", tags=["tenant-admin"])


def require_admin_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def _view(row: service.Tenant) -> TenantView:
    return TenantView(
        tenant_id=row.tenant_id,
        name=row.name,
        plan=row.plan,
        status=row.status,
        monthly_token_quota=row.monthly_token_quota,
        detail=row.detail,
        created_at=row.created_at,
    )


@router.post("", response_model=TenantView, status_code=201)
async def provision_tenant(
    body: TenantProvisionRequest,
    session: AsyncSession = Depends(get_session),
) -> TenantView:
    try:
        row = await service.provision_tenant(
            session,
            tenant_id=body.tenant_id,
            name=body.name,
            plan=body.plan,
            actor=body.actor,
        )
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.InvalidPlan as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.TenantExists as exc:
        raise HTTPException(status_code=409, detail=f"tenant already exists: {exc}") from exc
    await session.commit()
    return _view(row)


@router.get("", response_model=list[TenantView])
async def list_tenants(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_admin_view),
) -> list[TenantView]:
    rows = await service.list_tenants(session)
    return [_view(row) for row in rows]


@router.get("/{tenant_id}", response_model=TenantDetailView)
async def get_tenant(
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_admin_view),
) -> TenantDetailView:
    try:
        row = await service.get_tenant(session, tenant_id)
        progress = await service.onboarding_progress(session, tenant_id)
    except service.TenantNotFound as exc:
        raise HTTPException(status_code=404, detail=f"tenant not found: {exc}") from exc
    return TenantDetailView(**_view(row).model_dump(), onboarding=progress)


@router.post("/{tenant_id}/change-plan", response_model=TenantView)
async def change_plan(
    tenant_id: str,
    body: TenantChangePlanRequest,
    session: AsyncSession = Depends(get_session),
) -> TenantView:
    try:
        row = await service.change_plan(
            session, tenant_id=tenant_id, plan=body.plan, actor=body.actor
        )
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.InvalidPlan as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.TenantNotFound as exc:
        raise HTTPException(status_code=404, detail=f"tenant not found: {exc}") from exc
    await session.commit()
    return _view(row)


@router.post("/{tenant_id}/pause", response_model=TenantView)
async def pause_tenant(
    tenant_id: str,
    body: TenantLifecycleRequest,
    session: AsyncSession = Depends(get_session),
) -> TenantView:
    try:
        row = await service.pause_tenant(session, tenant_id=tenant_id, actor=body.actor)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.TenantNotFound as exc:
        raise HTTPException(status_code=404, detail=f"tenant not found: {exc}") from exc
    except service.IllegalTenantLifecycle as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return _view(row)


# Q114：客户侧只读账户面板（settings 页）——复用 Q95 租户注册表读服务，无 admin 闸、
# 无写审计（只读，同 Q98/Q99 客户读路径）；未知租户 404，暂停租户仍可读（面板需显 paused）。
customer_router = APIRouter(prefix="/api/tenants", tags=["tenant-customer"])


@customer_router.get("/{tenant_id}", response_model=CustomerTenantView)
async def get_current_tenant(
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
) -> CustomerTenantView:
    try:
        row = await service.get_tenant(session, tenant_id)
    except service.TenantNotFound as exc:
        raise HTTPException(status_code=404, detail=f"tenant not found: {exc}") from exc
    return CustomerTenantView(
        tenant_id=row.tenant_id,
        name=row.name,
        plan=row.plan,
        status=row.status,
        monthly_token_quota=row.monthly_token_quota,
    )


@router.post("/{tenant_id}/resume", response_model=TenantView)
async def resume_tenant(
    tenant_id: str,
    body: TenantLifecycleRequest,
    session: AsyncSession = Depends(get_session),
) -> TenantView:
    try:
        row = await service.resume_tenant(session, tenant_id=tenant_id, actor=body.actor)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.TenantNotFound as exc:
        raise HTTPException(status_code=404, detail=f"tenant not found: {exc}") from exc
    except service.IllegalTenantLifecycle as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return _view(row)
