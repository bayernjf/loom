from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.tenants import service as tenant_service
from app.product.product_intake import service
from app.product.product_intake.models import ProductSpace
from app.product.product_intake.schemas import (
    IntakeCreate,
    IntakeProfilePatch,
    IntakeTransition,
    IntakeView,
    ProductSpaceView,
)
from app.product.product_intake.statemachine import (
    IllegalTransition,
    RoleRequired,
    allowed_events,
)

router = APIRouter(prefix="/api/intakes", tags=["product-intake"])


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
    return IntakeView(
        intake_id=intake.intake_id,
        tenant_id=intake.tenant_id,
        status=intake.status,
        profile=intake.profile,
        category_pending_id=intake.category_pending_id,
    )


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
