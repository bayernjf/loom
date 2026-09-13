from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.compliance_wordlist import service
from app.core.compliance_wordlist.schemas import WordlistUpsert
from app.core.db import get_session

router = APIRouter(prefix="/api/admin/compliance-wordlist", tags=["compliance-wordlist"])


class _ArchiveBody(BaseModel):
    actor: Actor


def _view(e) -> dict:
    return {
        "entry_id": e.entry_id,
        "word": e.word,
        "level": e.level,
        "action": e.action,
        "downgrade_target": e.downgrade_target,
        "country": e.country,
        "industry": e.industry,
        "status": e.status,
    }


@router.get("")
async def list_entries(
    status: str = "active",
    level: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = await service.list_entries(session, status=status, level=level)
    return [_view(e) for e in rows]


@router.post("")
async def create_entry(
    body: WordlistUpsert, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        entry = await service.create_entry(session, body, body.actor)
        await session.commit()
    except service.WordlistForbidden as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _view(entry)


@router.put("/{entry_id}")
async def update_entry(
    entry_id: str, body: WordlistUpsert, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        entry = await service.update_entry(session, entry_id, body, body.actor)
        await session.commit()
    except service.EntryNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="wordlist entry not found") from exc
    except service.WordlistForbidden as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _view(entry)


@router.delete("/{entry_id}")
async def archive_entry(
    entry_id: str, body: _ArchiveBody, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        await service.archive_entry(session, entry_id, body.actor)
        await session.commit()
    except service.EntryNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="wordlist entry not found") from exc
    except service.WordlistForbidden as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"archived": entry_id}
