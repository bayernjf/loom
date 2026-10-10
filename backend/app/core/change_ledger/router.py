"""变更-回滚清单读口（Q334）：operations/platform_admin 只读。

GET 无请求体先例（agent-keys 列表不过闸）不适用治理面——照 Q92 dashboards /
Q326 管理端详情口先例，经 query 携带 actor（actor_id 必填，roles 可重复传），
缺 actor_id 由 FastAPI 判 422、角色不符判 403。V1 actor 自报口径（同写端点）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.change_ledger import service
from app.core.db import get_session
from app.core.rbac import OPERATIONS, PLATFORM_ADMIN, PermissionDenied, require_any_role

router = APIRouter(prefix="/api/admin/change-ledger", tags=["change-ledger"])


def require_change_ledger_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, OPERATIONS, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


@router.get("")
async def change_ledger(
    mechanism: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_change_ledger_view),
) -> dict:
    return await service.list_changes(
        session, mechanism=mechanism, limit=limit, offset=offset
    )
