"""Q38 降级动作字典管理面（docs/05 表行／docs/10 §dict_management「全部 CRUD＋审计」）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.downgrade_actions import service
from app.core.downgrade_actions.models import DowngradeAction
from app.core.downgrade_actions.schemas import DowngradeActionUpsert
from app.core.rbac import (
    DICTIONARY_ADMIN,
    OPERATIONS,
    PLATFORM_ADMIN,
    PermissionDenied,
    require_any_role,
)
from app.core.staff_auth.deps import require_internal_actor

router = APIRouter(prefix="/api/admin/downgrade-actions", tags=["downgrade-actions"])

_dict_gate = require_internal_actor(DICTIONARY_ADMIN)


def require_downgrade_actions_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    # Q118 同型读闸：缺 actor_id 422、越权 403。
    # 放三个角色是因为管理端一屏的自报身份来自 `LOOM_ADMIN_ROLES`（compose 默认只有
    # platform_admin）——只认 dictionary_admin 会让这屏一打开就 403，读面等于没有。
    # 写口不放行这条：仍只认字典管理员（docs/04 line 121／languages 先例）。
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, DICTIONARY_ADMIN, OPERATIONS, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def _view(row: DowngradeAction) -> dict:
    return {
        "code": row.code,
        "name": row.name,
        "why": row.why,
        "status": row.status,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
async def list_downgrade_actions(
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_downgrade_actions_view),
) -> list[dict]:
    rows = await service.list_actions(session, include_archived=include_archived)
    return [_view(r) for r in rows]


@router.put("")
async def upsert_downgrade_action(
    body: DowngradeActionUpsert,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_dict_gate),
) -> dict:
    try:
        row = await service.upsert_action(
            session, code=body.code, name=body.name, why=body.why, actor=verified
        )
    except service.ActionInvalid as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return _view(row)


@router.post("/{code}/archive")
async def archive_downgrade_action(
    code: str,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_dict_gate),
) -> dict:
    try:
        row = await service.archive_action(session, code, verified)
    except service.ActionNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="downgrade action not found") from exc
    await session.commit()
    return _view(row)
