from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_center import service
from app.core.config_center.config_rules import ConfigValidationError
from app.core.config_center.schemas import ConfigRollback, ConfigUpdate
from app.core.db import get_session

router = APIRouter(prefix="/api/admin/config", tags=["config-center"])


def _view(item) -> dict:
    return {
        "key": item.key,
        "category": item.category,
        "value": item.value,
        "value_type": item.value_type,
        "validation": item.validation,
        "source_ref": item.source_ref,
        "version": item.version,
        "updated_by": item.updated_by,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _version_view(row) -> dict:
    return {
        "version": row.version,
        "value": row.value,
        "change_note": row.change_note,
        "changed_by": row.changed_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
async def list_config(
    category: str | None = None, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    rows = await service.list_items(session, category=category)
    return [_view(item) for item in rows]


@router.get("/{key}")
async def get_config(key: str, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        item = await service.get_item(session, key)
    except service.ConfigKeyNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown config key {key}") from exc
    return _view(item)


@router.get("/{key}/history")
async def config_history(key: str, session: AsyncSession = Depends(get_session)) -> list[dict]:
    try:
        rows = await service.history(session, key)
    except service.ConfigKeyNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown config key {key}") from exc
    return [_version_view(row) for row in rows]


@router.put("/{key}")
async def update_config(
    key: str, body: ConfigUpdate, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        item = await service.update_item(session, key, body)
        await session.commit()
    except service.RoleNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ConfigKeyNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=f"unknown config key {key}") from exc
    except ConfigValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _view(item)


@router.post("/{key}/rollback")
async def rollback_config(
    key: str, body: ConfigRollback, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        item = await service.rollback_item(session, key, body)
        await session.commit()
    except service.RoleNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ConfigKeyNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=f"unknown config key {key}") from exc
    except service.ConfigVersionNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _view(item)
