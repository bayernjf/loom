from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.client_auth.deps import (
    ClientOrStaffCaller,
    require_client_or_staff_actor,
)
from app.core.db import get_session
from app.core.rbac import (
    OPERATIONS,
    PLATFORM_ADMIN,
    NotAuthenticated,
    PermissionDenied,
    require_any_role,
)
from app.core.tenants import service as tenant_service
from app.product.product_intake import service
from app.product.product_intake.models import ProductSpace
from app.product.product_intake.schemas import (
    IntakeCreate,
    IntakeList,
    IntakeOverview,
    IntakeProfilePatch,
    IntakeTargetLanguagesPatch,
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

# 评审 P1-1：录入单面不再接受零凭证 + 可猜测 tenant_id。双闸（客户令牌租户绑定 /
# staff 令牌 operations|platform_admin）由共享依赖实现，行级归属见 _enforce_tenant_scope。
# 自报 actor 一律作废：写路径身份以令牌验真结果为准。
IntakeCaller = ClientOrStaffCaller
require_intake_caller = require_client_or_staff_actor(OPERATIONS, PLATFORM_ADMIN)


def _enforce_tenant_scope(caller: IntakeCaller, row_tenant_id: str) -> None:
    """客户令牌只许碰本租户的行；跨租户一律 404，不泄露存在性。"""
    if caller.tenant_id is not None and row_tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="intake not found")


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
    _: IntakeCaller = Depends(require_intake_caller),
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
    _: IntakeCaller = Depends(require_intake_caller),
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
    body: IntakeCreate,
    session: AsyncSession = Depends(get_session),
    caller: IntakeCaller = Depends(require_intake_caller),
) -> IntakeView:
    # 客户令牌只许为本租户建单（与令牌归属不符统一 401，不泄露租户存在性）；
    # staff 令牌（operations/platform_admin）可为任一注册租户建单。
    if caller.tenant_id is not None and body.tenant_id != caller.tenant_id:
        raise NotAuthenticated(
            "valid client access token for this tenant required "
            "(self-declared actor is not identity)"
        )
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
    intake_id: str,
    session: AsyncSession = Depends(get_session),
    caller: IntakeCaller = Depends(require_intake_caller),
) -> IntakeView:
    try:
        intake = await service.get_intake(session, intake_id)
    except service.IntakeNotFound:
        raise HTTPException(status_code=404, detail="intake not found")
    _enforce_tenant_scope(caller, intake.tenant_id)
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
    caller: IntakeCaller = Depends(require_intake_caller),
) -> IntakeView:
    try:
        existing = await service.get_intake(session, intake_id)
    except service.IntakeNotFound:
        raise HTTPException(status_code=404, detail="intake not found")
    _enforce_tenant_scope(caller, existing.tenant_id)
    try:
        intake = await service.update_profile(
            session,
            intake_id=intake_id,
            profile_patch=body.profile,
            actor_id=caller.actor.id,
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
    intake_id: str,
    session: AsyncSession = Depends(get_session),
    caller: IntakeCaller = Depends(require_intake_caller),
) -> dict:
    try:
        intake = await service.get_intake(session, intake_id)
    except service.IntakeNotFound:
        raise HTTPException(status_code=404, detail="intake not found")
    _enforce_tenant_scope(caller, intake.tenant_id)
    return {"status": intake.status, "allowed_events": allowed_events(intake.status)}


@router.post("/{intake_id}/transitions", response_model=IntakeView)
async def transition_intake(
    intake_id: str,
    body: IntakeTransition,
    session: AsyncSession = Depends(get_session),
    caller: IntakeCaller = Depends(require_intake_caller),
) -> IntakeView:
    try:
        existing = await service.get_intake(session, intake_id)
    except service.IntakeNotFound:
        raise HTTPException(status_code=404, detail="intake not found")
    _enforce_tenant_scope(caller, existing.tenant_id)
    try:
        intake = await service.apply_event(
            session,
            intake_id=intake_id,
            event=body.event,
            actor_id=caller.actor.id,
            actor_roles=caller.actor.roles,
            category_pending_id=body.category_pending_id,
        )
    except service.IntakeNotFound:
        raise HTTPException(status_code=404, detail="intake not found")
    except service.MissingRequiredFields as exc:
        raise HTTPException(status_code=422, detail={"missing_fids": exc.missing})
    except service.InvalidContentUsage as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    intake_id: str,
    session: AsyncSession = Depends(get_session),
    caller: IntakeCaller = Depends(require_intake_caller),
) -> ProductSpaceView:
    space = await session.scalar(
        select(ProductSpace).where(ProductSpace.intake_id == intake_id)
    )
    if space is None:
        raise HTTPException(status_code=404, detail="product space not created yet")
    _enforce_tenant_scope(caller, space.tenant_id)
    return ProductSpaceView(
        product_space_id=space.product_space_id,
        tenant_id=space.tenant_id,
        intake_id=space.intake_id,
        lifecycle=space.lifecycle,
        profile_snapshot=space.profile_snapshot,
        target_languages=space.target_languages,
    )


@router.patch("/{intake_id}/target-languages", response_model=ProductSpaceView)
async def patch_target_languages(
    intake_id: str,
    tenant_id: str = Query(min_length=1),
    body: IntakeTargetLanguagesPatch = ...,
    session: AsyncSession = Depends(get_session),
    caller: IntakeCaller = Depends(require_intake_caller),
) -> ProductSpaceView:
    """B3/Q122：客户在段1 录入页设置产品目标语言（客户口径，无运营闸）。
    Q200 #32：必填 tenant_id，与产品空间归属不符统一 404。
    P1-1：身份以令牌验真为准（caller.actor），body 自报 actor 不再作数。"""
    try:
        space = await service.set_target_languages(
            session,
            intake_id=intake_id,
            tenant_id=tenant_id,
            languages=body.languages,
            actor=caller.actor,
        )
    except service.ProductSpaceNotCreated:
        raise HTTPException(
            status_code=404, detail="product space not created yet"
        ) from None
    except service.TargetLanguagesInvalid as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProductSpaceView(
        product_space_id=space.product_space_id,
        tenant_id=space.tenant_id,
        intake_id=space.intake_id,
        lifecycle=space.lifecycle,
        profile_snapshot=space.profile_snapshot,
        target_languages=space.target_languages,
    )
