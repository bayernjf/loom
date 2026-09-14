"""段9 三包配置实例 REST 端点（V1 静态切片，08 M11）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.decision.layer_strategy import service
from app.decision.layer_strategy.schemas import (
    ActorOnly,
    PackageCreate,
    PackageUpdate,
)

router = APIRouter(tags=["layer-strategy"])


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
) -> dict:
    try:
        package = await service.create_package(session, product_space_id, body, body.actor)
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
    package_id: str, body: PackageUpdate, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        package = await service.update_package(session, package_id, body, body.actor)
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
    package_id: str, body: ActorOnly, session: AsyncSession = Depends(get_session)
) -> None:
    try:
        await service.archive_package(session, package_id, body.actor)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.PackageNotFound as exc:
        raise HTTPException(404, f"package not found: {exc}") from exc
    await session.commit()
