from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.rbac import OPERATIONS, PLATFORM_ADMIN, PermissionDenied, require_any_role
from app.core.tenants import service as tenant_service
from app.product.product_intake import service
from app.product.product_intake.models import ProductSpace
from app.product.product_intake.schemas import (
    IntakeCreate,
    IntakeList,
    IntakeOverview,
    IntakeProfilePatch,
    IntakeTransition,
    IntakeView,
    OpsIntakeList,
    OpsIntakeView,
    ProductSpaceView,
)
from app.product.product_intake.statemachine import (
    STATE_LABELS,
    IllegalTransition,
    RoleRequired,
    allowed_events,
)

router = APIRouter(prefix="/api/intakes", tags=["product-intake"])


def require_ops_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    # Q107：运营跨租户队列只读，operations 与 platform_admin 可见。
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, OPERATIONS, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def _to_view(intake) -> IntakeView:
    return IntakeView(
        intake_id=intake.intake_id,
        tenant_id=intake.tenant_id,
        status=intake.status,
        profile=intake.profile,
        category_pending_id=intake.category_pending_id,
    )


@router.get("", response_model=IntakeList)
async def list_intakes(
    tenant_id: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> IntakeList:
    # Q98：按租户只读列表；读路径不触发 Q95 准入门，未知租户返回空列表。
    items, total = await service.list_intakes(
        session, tenant_id=tenant_id, limit=limit, offset=offset
    )
    return IntakeList(
        items=[_to_view(intake) for intake in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/overview", response_model=IntakeOverview)
async def overview_intakes(
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
) -> IntakeOverview:
    # Q99：工作台总览。必须注册在 /{intake_id} 之前，否则会被路径参数吞掉。
    # 读路径与 Q98 列表同口径：不触发 Q95 准入门，未知租户返回零值。
    total, by_status = await service.overview_intakes(session, tenant_id=tenant_id)
    return IntakeOverview(total=total, by_status=by_status)


@router.get("/ops-queue", response_model=OpsIntakeList)
async def list_ops_intakes(
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_ops_view),
) -> OpsIntakeList:
    # Q107：运营跨租户队列；必须注册在 /{intake_id} 之前以免被路径参数吞掉。
    if status is not None and status not in STATE_LABELS:
        raise HTTPException(status_code=422, detail=f"unknown intake status: {status}")
    items, total = await service.list_ops_intakes(
        session, status=status, limit=limit, offset=offset
    )
    return OpsIntakeList(
        items=[
            OpsIntakeView(
                intake_id=item.intake_id,
                tenant_id=item.tenant_id,
                status=item.status,
                profile=item.profile,
                category_pending_id=item.category_pending_id,
                created_at=item.created_at,
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=IntakeView, status_code=201)
async def create_intake(
    body: IntakeCreate, session: AsyncSession = Depends(get_session)
) -> IntakeView:
    try:
        intake = await service.create_intake(
            session, tenant_id=body.tenant_id, profile=body.profile
        )
    except tenant_service.TenantNotFound as exc:
        raise HTTPException(status_code=404, detail=f"tenant not found: {exc}") from exc
    except tenant_service.TenantPaused as exc:
        raise HTTPException(status_code=409, detail=f"tenant is paused: {exc}") from exc
    return _to_view(intake)


@router.get("/{intake_id}", response_model=IntakeView)
async def get_intake(
    intake_id: str, session: AsyncSession = Depends(get_session)
) -> IntakeView:
    try:
        intake = await service.get_intake(session, intake_id)
    except service.IntakeNotFound:
        raise HTTPException(status_code=404, detail="intake not found")
    return IntakeView(
        intake_id=intake.intake_id,
        tenant_id=intake.tenant_id,
        status=intake.status,
        profile=intake.profile,
        category_pending_id=intake.category_pending_id,
    )


@router.patch("/{intake_id}/profile", response_model=IntakeView)
async def patch_profile(
    intake_id: str,
    body: IntakeProfilePatch,
    session: AsyncSession = Depends(get_session),
) -> IntakeView:
    try:
        intake = await service.update_profile(
            session,
            intake_id=intake_id,
            profile_patch=body.profile,
            actor_id=body.actor.id,
        )
    except service.IntakeNotFound:
        raise HTTPException(status_code=404, detail="intake not found")
    except service.ProfileNotEditable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return IntakeView(
        intake_id=intake.intake_id,
        tenant_id=intake.tenant_id,
        status=intake.status,
        profile=intake.profile,
        category_pending_id=intake.category_pending_id,
    )


@router.get("/{intake_id}/allowed-events")
async def get_allowed_events(
    intake_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        intake = await service.get_intake(session, intake_id)
    except service.IntakeNotFound:
        raise HTTPException(status_code=404, detail="intake not found")
    return {"status": intake.status, "allowed_events": allowed_events(intake.status)}


@router.post("/{intake_id}/transitions", response_model=IntakeView)
async def transition_intake(
    intake_id: str,
    body: IntakeTransition,
    session: AsyncSession = Depends(get_session),
) -> IntakeView:
    try:
        intake = await service.apply_event(
            session,
            intake_id=intake_id,
            event=body.event,
            actor_id=body.actor.id,
            actor_roles=body.actor.roles,
            category_pending_id=body.category_pending_id,
        )
    except service.IntakeNotFound:
        raise HTTPException(status_code=404, detail="intake not found")
    except service.MissingRequiredFields as exc:
        raise HTTPException(status_code=422, detail={"missing_fids": exc.missing})
    except RoleRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return IntakeView(
        intake_id=intake.intake_id,
        tenant_id=intake.tenant_id,
        status=intake.status,
        profile=intake.profile,
        category_pending_id=intake.category_pending_id,
    )


@router.get("/{intake_id}/product-space", response_model=ProductSpaceView)
async def get_product_space(
    intake_id: str, session: AsyncSession = Depends(get_session)
) -> ProductSpaceView:
    space = await session.scalar(
        select(ProductSpace).where(ProductSpace.intake_id == intake_id)
    )
    if space is None:
        raise HTTPException(status_code=404, detail="product space not created yet")
    return ProductSpaceView(
        product_space_id=space.product_space_id,
        tenant_id=space.tenant_id,
        intake_id=space.intake_id,
        lifecycle=space.lifecycle,
        profile_snapshot=space.profile_snapshot,
    )
