"""内部运营个人令牌治理端点 + 登录身份自检（Q178，甲案 PAT）。

- POST/GET/ revoke ``/api/admin/staff-keys``：platform_admin 红线，明文仅签发回一次。
- GET ``/api/auth/me``：门控开启后供登录录入页校验令牌并回显人员/角色。

门控关闭时治理端点沿用 V1 actor 自报（query/body）口径——**首个 platform_admin
人员令牌必须在门控仍关时由此签发（引导）**；门控开启后这些端点的内部角色闸改由
rbac 以 Bearer staff 令牌验真（自报失效），见 docs/17 引导顺序。
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session, settings
from app.core.rbac import PLATFORM_ADMIN, PermissionDenied, require_any_role
from app.core.staff_auth import service
from app.core.staff_auth.deps import get_auth_session
from app.core.staff_auth.schemas import (
    StaffKeyIssued,
    StaffKeyIssueRequest,
    StaffKeyRevokeRequest,
    StaffKeyView,
    StaffMe,
)

router = APIRouter(tags=["staff-auth"])


def _view(row) -> StaffKeyView:
    return StaffKeyView(
        key_id=row.key_id,
        staff_id=row.staff_id,
        staff_name=row.staff_name,
        roles=list(row.roles),
        key_prefix=row.key_prefix,
        status=row.status,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
    )


def require_admin_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    """管理面读口 actor 闸（门控关 query 自报；门控开 rbac 以令牌身份覆盖）。"""
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


@router.post(
    "/api/admin/staff-keys",
    response_model=StaffKeyIssued,
    status_code=201,
)
async def issue_staff_key(
    body: StaffKeyIssueRequest,
    session: AsyncSession = Depends(get_session),
) -> StaffKeyIssued:
    try:
        row, secret = await service.issue_staff_key(
            session,
            staff_id=body.staff_id,
            staff_name=body.staff_name,
            roles=body.roles,
            actor=body.actor,
        )
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(row)
    return StaffKeyIssued(**_view(row).model_dump(), secret=secret)


@router.get("/api/admin/staff-keys", response_model=list[StaffKeyView])
async def list_staff_keys(
    include_revoked: bool = False,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_admin_view),
) -> list[StaffKeyView]:
    rows = await service.list_staff_keys(session, include_revoked=include_revoked)
    return [_view(row) for row in rows]


@router.post(
    "/api/admin/staff-keys/{key_id}/revoke",
    response_model=StaffKeyView,
)
async def revoke_staff_key(
    key_id: str,
    body: StaffKeyRevokeRequest,
    session: AsyncSession = Depends(get_session),
) -> StaffKeyView:
    try:
        row = await service.revoke_staff_key(session, key_id, body.actor)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.StaffKeyNotFound as exc:
        raise HTTPException(status_code=404, detail="staff API key not found") from exc
    await session.commit()
    return _view(row)


@router.get("/api/auth/me", response_model=StaffMe)
async def auth_me(
    authorization: str | None = Header(default=None),
    auth_session: AsyncSession | None = Depends(get_auth_session),
) -> StaffMe:
    """登录录入页自检：用 staff 令牌换回人员/角色。门控关闭返回 400。"""
    if not settings.staff_auth_enabled:
        raise HTTPException(status_code=400, detail="staff authentication is disabled")
    token = service.parse_bearer(authorization)
    if not token or not service.is_staff_token(token):
        raise HTTPException(status_code=401, detail="staff access token required")
    row = await service.verify_staff_key(auth_session, token)
    if row is None:
        raise HTTPException(status_code=401, detail="invalid or revoked staff token")
    await auth_session.commit()
    return StaffMe(staff_id=row.staff_id, staff_name=row.staff_name, roles=list(row.roles))
