"""入站 Agent Key 治理端点（Q88；platform_admin 红线）。

仅签发/列表/吊销；受 Key 保护的业务端点（POST /api/effect-callback）
随段13/P3 V2，见 05 §1.1.1。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_keys import service
from app.core.api_keys.schemas import (
    AgentKeyIssued,
    AgentKeyIssueRequest,
    AgentKeyRevokeRequest,
    AgentKeyView,
)
from app.core.db import get_session
from app.core.rbac import PLATFORM_ADMIN, PermissionDenied
from app.core.staff_auth.deps import internal_gate

router = APIRouter(tags=["agent-api-keys"])


def _view(row) -> AgentKeyView:
    return AgentKeyView(
        key_id=row.key_id,
        name=row.name,
        key_prefix=row.key_prefix,
        status=row.status,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


@router.post(
    "/api/admin/agent-keys",
    response_model=AgentKeyIssued,
    status_code=201,
)
async def issue_agent_key(
    body: AgentKeyIssueRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentKeyIssued:
    try:
        row, secret = await service.issue_key(session, body.name, body.actor)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(row)
    return AgentKeyIssued(**_view(row).model_dump(), secret=secret)


@router.get("/api/admin/agent-keys", response_model=list[AgentKeyView])
async def list_agent_keys(
    include_revoked: bool = False,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(internal_gate(PLATFORM_ADMIN)),
) -> list[AgentKeyView]:
    # GET 门控关无 actor 体（Q109 有意开放，与 outbound Key 列表同口径，写操作过
    # 角色闸）；Q178 门控开启后由 internal_gate 要求 platform_admin staff 令牌。
    rows = await service.list_keys(session, include_revoked=include_revoked)
    return [_view(row) for row in rows]


@router.post(
    "/api/admin/agent-keys/{key_id}/revoke",
    response_model=AgentKeyView,
)
async def revoke_agent_key(
    key_id: str,
    body: AgentKeyRevokeRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentKeyView:
    try:
        row = await service.revoke_key(session, key_id, body.actor)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.AgentKeyNotFound as exc:
        raise HTTPException(status_code=404, detail="agent API key not found") from exc
    await session.commit()
    return _view(row)
