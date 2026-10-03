"""段9 三包配置实例 + Q262 layerSpaces 通用底座 REST 端点（V1 静态切片 08 M11 / Q46）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.rbac import OPERATIONS, PLATFORM_ADMIN, PermissionDenied, require_any_role
from app.core.staff_auth.deps import require_internal_actor
from app.decision.layer_strategy import service
from app.decision.layer_strategy.schemas import (
    ActorOnly,
    LayerSpaceItemArchive,
    LayerSpaceItemCreate,
    LayerSpaceItemUpdate,
    PackageCreate,
    PackageUpdate,
)

router = APIRouter(tags=["layer-strategy"])

# Q242：三包写口只认已验真 staff 令牌；service 层 _require_ops 保留作兜底。
_ops_gate = require_internal_actor(OPERATIONS)
# Q262（Q46）：layerSpaces 增删改仅平台级管理员。
_admin_gate = require_internal_actor(PLATFORM_ADMIN)


def require_layer_spaces_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    # Q46：layerSpaces 普通运营只读（platform_admin 当然可读）——管理面读口同
    # Q109/Q118 口径补 query actor 闸。
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, OPERATIONS, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def _package_view(p) -> dict:
    return {
        "package_id": p.package_id,
        "kind": p.kind,
        "tenant_id": p.tenant_id,
        "product_space_id": p.product_space_id,
        "platform": p.platform,
        "goal": p.goal,
        "payload": p.payload,
        "conf": p.conf,
        "gate": p.gate,
        "status": p.status,
        "usage_count": p.usage_count,
    }


@router.get("/api/product-spaces/{product_space_id}/packages")
async def list_packages(
    product_space_id: str,
    platform: str | None = None,
    goal: str | None = None,
    status: str | None = "active",
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return [
        _package_view(p)
        for p in await service.list_packages(
            session, product_space_id, platform=platform, goal=goal, status=status
        )
    ]


@router.post("/api/product-spaces/{product_space_id}/packages", status_code=201)
async def create_package(
    product_space_id: str,
    body: PackageCreate,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        package = await service.create_package(session, product_space_id, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.PsNotFound as exc:
        raise HTTPException(404, f"product space not found: {exc}") from exc
    except service.GoalNotFound as exc:
        raise HTTPException(404, f"goal not found or archived: {exc}") from exc
    except service.PackageExists as exc:
        raise HTTPException(409, f"active package exists for triple: {exc}") from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    await session.commit()
    return _package_view(package)


@router.put("/api/packages/{package_id}")
async def update_package(
    package_id: str,
    body: PackageUpdate,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        package = await service.update_package(session, package_id, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.PackageNotFound as exc:
        raise HTTPException(404, f"package not found: {exc}") from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    await session.commit()
    return _package_view(package)


@router.delete("/api/packages/{package_id}", status_code=204)
async def archive_package(
    package_id: str,
    body: ActorOnly,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> None:
    try:
        await service.archive_package(session, package_id, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.PackageNotFound as exc:
        raise HTTPException(404, f"package not found: {exc}") from exc
    await session.commit()


# Q264（Q45 重配载体甲）：运营待重配清单只读口——管理面读口同 Q109/Q118 口径
# 补 query actor 闸（operations|platform_admin 只读），人工更新包 payload 清零后
# 自然移出清单。语义与排期见 docs/design-p2-package-reuse-reconfig.md §3.1 甲。
@router.get("/api/admin/packages/reuse-pending")
async def list_reuse_pending(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_layer_spaces_view),
) -> list[dict]:
    return await service.list_reuse_pending(session)


# ---------------------------------------------------------------------------
# Q262 layerSpaces 通用底座（Q46）
# ---------------------------------------------------------------------------


def _layer_view(layer) -> dict:
    return {
        "layer_id": layer.layer_id,
        "code": layer.code,
        "name": layer.name,
        "dimensions": layer.dimensions,
        "sort_order": layer.sort_order,
    }


def _item_view(item) -> dict:
    return {
        "item_id": item.item_id,
        "layer_id": item.layer_id,
        "dimension": item.dimension,
        "name": item.name,
        "status": item.status,
    }


@router.get("/api/admin/layer-spaces")
async def list_layer_spaces(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_layer_spaces_view),
) -> list[dict]:
    layers = await service.list_layer_spaces(session)
    items = await service.list_items(session)
    by_layer: dict[str, list[dict]] = {}
    for it in items:
        by_layer.setdefault(it.layer_id, []).append(_item_view(it))
    return [{**_layer_view(l), "items": by_layer.get(l.layer_id, [])} for l in layers]


@router.get("/api/admin/layer-spaces/items/{item_id}/impact")
async def get_item_impact(
    item_id: str,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_layer_spaces_view),
) -> dict:
    try:
        item = await service.get_item(session, item_id)
    except service.LayerItemNotFound as exc:
        raise HTTPException(404, f"layer space item not found: {exc}") from exc
    return {"item_id": item_id, "active_package_refs": await service.item_refs(session, item)}


@router.post("/api/admin/layer-spaces/items", status_code=201)
async def create_layer_item(
    body: LayerSpaceItemCreate,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_admin_gate),
) -> dict:
    try:
        item = await service.create_item(session, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.LayerNotFound as exc:
        raise HTTPException(404, f"layer space not found: {exc}") from exc
    except service.LayerItemExists as exc:
        raise HTTPException(409, f"layer space item exists: {exc}") from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    await session.commit()
    return _item_view(item)


@router.put("/api/admin/layer-spaces/items/{item_id}")
async def update_layer_item(
    item_id: str,
    body: LayerSpaceItemUpdate,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_admin_gate),
) -> dict:
    try:
        item = await service.update_item(session, item_id, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.LayerItemNotFound as exc:
        raise HTTPException(404, f"layer space item not found: {exc}") from exc
    except service.ImpactRequiresConfirmation as exc:
        raise HTTPException(
            409,
            {"active_package_refs": exc.refs, "impact_confirmed": False},
        ) from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    await session.commit()
    return _item_view(item)


@router.delete("/api/admin/layer-spaces/items/{item_id}", status_code=204)
async def archive_layer_item(
    item_id: str,
    body: LayerSpaceItemArchive,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_admin_gate),
) -> None:
    try:
        await service.archive_item(session, item_id, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.LayerItemNotFound as exc:
        raise HTTPException(404, f"layer space item not found: {exc}") from exc
    except service.ImpactRequiresConfirmation as exc:
        raise HTTPException(
            409,
            {"active_package_refs": exc.refs, "impact_confirmed": False},
        ) from exc
    await session.commit()
