"""段3 灵感库路由：运营配置 CRUD（内部角色闸，与客户侧隔离）。

端点（均为 /api/admin 内部面）：
- GET  /admin/inspiration-entries          列表（按 tenant/layer/product_space_id/enabled 过滤）
- POST /admin/inspiration-entries          新建（common/product 两层）
- PUT  /admin/inspiration-entries/{id}     更新（content/tags/enabled）
- DELETE /admin/inspiration-entries/{id}   删除
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.rbac import OPERATIONS, PLATFORM_ADMIN, PermissionDenied, require_any_role
from app.product.inspiration import service
from app.product.inspiration.schemas import (
    InspirationCreate,
    InspirationDelete,
    InspirationUpdate,
)
from app.product.product_intake.schemas import Actor

router = APIRouter(prefix="/api", tags=["inspiration"])


def require_inspiration_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, OPERATIONS, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def _view(e) -> dict:
    return {
        "entry_id": e.entry_id,
        "tenant_id": e.tenant_id,
        "layer": e.layer,
        "product_space_id": e.product_space_id,
        "content": e.content,
        "tags": e.tags,
        "enabled": e.enabled,
        "usage_count": e.usage_count,
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }


@router.get("/admin/inspiration-entries")
async def list_entries(
    tenant_id: str = Query(...),
    layer: str | None = None,
    product_space_id: str | None = None,
    enabled: bool | None = None,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_inspiration_view),
) -> list[dict]:
    rows = await service.list_entries(
        session,
        tenant_id=tenant_id,
        layer=layer,
        product_space_id=product_space_id,
        enabled=enabled,
    )
    return [_view(r) for r in rows]


@router.post("/admin/inspiration-entries", status_code=201)
async def create_entry(
    body: InspirationCreate, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        entry = await service.create_entry(
            session,
            tenant_id=body.tenant_id,
            layer=body.layer,
            product_space_id=body.product_space_id,
            content=body.content,
            tags=body.tags,
            enabled=body.enabled,
            actor=body.actor,
        )
        await session.commit()
    except service.InvalidInspiration as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _view(entry)


@router.put("/admin/inspiration-entries/{entry_id}")
async def update_entry(
    entry_id: str,
    body: InspirationUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        entry = await service.update_entry(
            session,
            entry_id,
            content=body.content,
            tags=body.tags,
            enabled=body.enabled,
            actor=body.actor,
        )
        await session.commit()
    except service.EntryNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="inspiration entry not found") from exc
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _view(entry)


@router.delete("/admin/inspiration-entries/{entry_id}")
async def delete_entry(
    entry_id: str,
    body: InspirationDelete,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        await service.delete_entry(session, entry_id, body.actor)
        await session.commit()
    except service.EntryNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="inspiration entry not found") from exc
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"deleted": entry_id}
