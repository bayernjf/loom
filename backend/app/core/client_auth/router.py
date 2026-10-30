"""客户访问令牌治理端点（P0，2026-10-30）。

- POST/GET/revoke ``/api/admin/client-keys``：内部运营红线（platform_admin |
  operations），明文仅签发回一次。
- 门控关闭时沿用 V1 actor 自报（query/body）口径完成引导签发；门控开启后内部角色
  闸由 rbac 以 Bearer staff 令牌验真（自报失效）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.client_auth import service
from app.core.client_auth.schemas import (
    ClientKeyIssued,
    ClientKeyIssueRequest,
    ClientKeyRevokeRequest,
    ClientKeyView,
)
from app.core.db import get_session
from app.core.rbac import OPERATIONS, PLATFORM_ADMIN, PermissionDenied, require_any_role

router = APIRouter(tags=["client-auth"])


def _view(row) -> ClientKeyView:
    return ClientKeyView(
        token_id=row.token_id,
        tenant_id=row.tenant_id,
        client_name=row.client_name,
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
        require_any_role(actor, PLATFORM_ADMIN, OPERATIONS)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


@router.post(
    "/api/admin/client-keys", response_model=ClientKeyIssued, status_code=201
)
async def issue_client_key(
    body: ClientKeyIssueRequest,
    session: AsyncSession = Depends(get_session),
) -> ClientKeyIssued:
    try:
        row, secret = await service.issue_client_key(
            session,
            tenant_id=body.tenant_id,
            client_name=body.client_name,
            actor=body.actor,
        )
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(row)
    return ClientKeyIssued(**_view(row).model_dump(), secret=secret)


@router.get("/api/admin/client-keys", response_model=list[ClientKeyView])
async def list_client_keys(
    tenant_id: str | None = Query(default=None),
    include_revoked: bool = False,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_admin_view),
) -> list[ClientKeyView]:
    rows = await service.list_client_keys(
        session, tenant_id=tenant_id, include_revoked=include_revoked
    )
    return [_view(row) for row in rows]


@router.post(
    "/api/admin/client-keys/{token_id}/revoke", response_model=ClientKeyView
)
async def revoke_client_key(
    token_id: str,
    body: ClientKeyRevokeRequest,
    session: AsyncSession = Depends(get_session),
) -> ClientKeyView:
    try:
        row = await service.revoke_client_key(session, token_id, body.actor)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ClientKeyNotFound as exc:
        raise HTTPException(status_code=404, detail="client access token not found") from exc
    await session.commit()
    return _view(row)
