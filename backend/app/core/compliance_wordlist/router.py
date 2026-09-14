from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.compliance_wordlist import service
from app.core.compliance_wordlist.schemas import WordlistUpsert
from app.core.db import get_session

router = APIRouter(prefix="/api/admin/compliance-wordlist", tags=["compliance-wordlist"])


async def _q51_rescan(session, entry) -> list[dict]:
    # Q51：词表保存生效即扫 active 快照（边沿接线，避免 core 反向依赖 decision 包）。
    from app.decision.compliance_center.service import rescan_for_entry

    return await rescan_for_entry(session, entry)


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
        "layer": e.layer,
        "status": e.status,
        "effective_from": e.effective_from.isoformat() if e.effective_from else None,
        "effective_until": e.effective_until.isoformat() if e.effective_until else None,
        "activated_at": e.activated_at.isoformat() if e.activated_at else None,
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
        impacted = await _q51_rescan(session, entry)
        await session.commit()
    except service.WordlistForbidden as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**_view(entry), "q51_impacted": impacted}


@router.put("/{entry_id}")
async def update_entry(
    entry_id: str, body: WordlistUpsert, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        entry = await service.update_entry(session, entry_id, body, body.actor)
        impacted = await _q51_rescan(session, entry)
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
    return {**_view(entry), "q51_impacted": impacted}


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
