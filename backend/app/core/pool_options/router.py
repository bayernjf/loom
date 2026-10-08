"""Q43 17 池选项字典管理面（docs/10 §dict_management「全部 CRUD＋审计」）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.pool_options import service
from app.core.pool_options.models import PoolOption
from app.core.pool_options.schemas import PoolOptionUpsert
from app.core.rbac import (
    DICTIONARY_ADMIN,
    OPERATIONS,
    PLATFORM_ADMIN,
    PermissionDenied,
    require_any_role,
)
from app.core.staff_auth.deps import require_internal_actor

router = APIRouter(prefix="/api/admin/pool-options", tags=["pool-options"])

_dict_gate = require_internal_actor(DICTIONARY_ADMIN)


def require_pool_options_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    # Q118 同型读闸；放行 platform_admin 是 Q307 定的规矩——管理端唯一保证存在的身份
    # 就是它，只认 dictionary_admin 会让这一屏打开即 403。写口仍只认字典管理员。
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, DICTIONARY_ADMIN, OPERATIONS, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def _view(row: PoolOption) -> dict:
    return {
        "pool": row.pool,
        "options": list(row.options or []),
        "status": row.status,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
async def list_pool_options(
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_pool_options_view),
) -> list[dict]:
    rows = await service.list_pools(session, include_archived=include_archived)
    return [_view(r) for r in rows]


@router.put("")
async def upsert_pool_option(
    body: PoolOptionUpsert,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_dict_gate),
) -> dict:
    try:
        row = await service.upsert_pool(
            session, pool=body.pool, options=body.options, actor=verified
        )
    except service.PoolInvalid as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return _view(row)


@router.post("/{pool}/archive")
async def archive_pool_option(
    pool: str,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_dict_gate),
) -> dict:
    try:
        row = await service.archive_pool(session, pool, verified)
    except service.PoolNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="pool not found") from exc
    await session.commit()
    return _view(row)
