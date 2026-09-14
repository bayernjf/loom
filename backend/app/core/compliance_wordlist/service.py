"""Q48 统一合规词库服务：CRUD + 生效词条匹配（段4/5/10 三关卡同源）。

第一期匹配为确定性子串匹配（M4 无 AI）；生效期/国家/行业过滤在此统一实现。
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.compliance_wordlist.models import ComplianceWordlistEntry
from app.product.atom.atom_rules import WordlistHit

PLATFORM_TENANT = "_platform"

_LAYERS = {"country", "platform", "base"}


def _normalize_layer(layer: str | None, country: str | None) -> str:
    if layer is not None:
        if layer not in _LAYERS:
            raise ValueError(f"unknown compliance layer: {layer}")
        return layer
    return "country" if country else "base"


class EntryNotFound(Exception):
    pass


class WordlistForbidden(Exception):
    pass


async def list_entries(
    session: AsyncSession,
    *,
    status: str = "active",
    level: str | None = None,
) -> Sequence[ComplianceWordlistEntry]:
    stmt = select(ComplianceWordlistEntry)
    if status is not None:
        stmt = stmt.where(ComplianceWordlistEntry.status == status)
    if level is not None:
        stmt = stmt.where(ComplianceWordlistEntry.level == level)
    return (await session.scalars(stmt.order_by(ComplianceWordlistEntry.created_at))).all()


def _in_effective_window(item, now: datetime) -> bool:
    return not (
        (item.effective_from is not None and item.effective_from > now)
        or (item.effective_until is not None and item.effective_until < now)
    )


async def create_entry(session, body, actor) -> ComplianceWordlistEntry:
    if not (set(actor.roles) & {"operations", "internal_compliance"}):
        raise WordlistForbidden("wordlist edit requires operations/internal_compliance")
    if body.item.action == "downgrade" and not (body.item.downgrade_target or "").strip():
        raise ValueError("downgrade_target is required when action=downgrade")
    layer = _normalize_layer(body.item.layer, body.item.country)
    now = datetime.now(UTC)
    entry = ComplianceWordlistEntry(
        word=body.item.word,
        level=body.item.level,
        action=body.item.action,
        downgrade_target=body.item.downgrade_target,
        country=body.item.country,
        industry=body.item.industry,
        layer=layer,
        effective_from=body.item.effective_from,
        effective_until=body.item.effective_until,
        activated_at=now if _in_effective_window(body.item, now) else None,
        created_by=actor.id,
    )
    session.add(entry)
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="wl.create",
        entity_type="compliance_wordlist",
        entity_id=entry.entry_id,
        detail={"word": entry.word, "level": entry.level, "action": entry.action},
    )
    return entry


async def update_entry(session, entry_id: str, body, actor) -> ComplianceWordlistEntry:
    if not (set(actor.roles) & {"operations", "internal_compliance"}):
        raise WordlistForbidden("wordlist edit requires operations/internal_compliance")
    entry = await session.get(ComplianceWordlistEntry, entry_id)
    if entry is None:
        raise EntryNotFound(entry_id)
    if body.item.action == "downgrade" and not (body.item.downgrade_target or "").strip():
        raise ValueError("downgrade_target is required when action=downgrade")
    entry.word = body.item.word
    entry.level = body.item.level
    entry.action = body.item.action
    entry.downgrade_target = body.item.downgrade_target
    entry.country = body.item.country
    entry.industry = body.item.industry
    entry.layer = _normalize_layer(body.item.layer, body.item.country)
    entry.effective_from = body.item.effective_from
    entry.effective_until = body.item.effective_until
    now = datetime.now(UTC)
    entry.activated_at = now if _in_effective_window(body.item, now) else None
    entry.status = "active"
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="wl.update",
        entity_type="compliance_wordlist",
        entity_id=entry_id,
        detail={"word": entry.word, "level": entry.level, "action": entry.action},
    )
    return entry


async def archive_entry(session, entry_id: str, actor) -> None:
    if not (set(actor.roles) & {"operations", "internal_compliance"}):
        raise WordlistForbidden("wordlist edit requires operations/internal_compliance")
    entry = await session.get(ComplianceWordlistEntry, entry_id)
    if entry is None:
        raise EntryNotFound(entry_id)
    entry.status = "archived"
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="wl.archive",
        entity_type="compliance_wordlist",
        entity_id=entry_id,
        detail={"word": entry.word},
    )


async def active_entries(
    session: AsyncSession, *, industry: str | None, now: datetime
) -> Sequence[ComplianceWordlistEntry]:
    """适用于该行业、当前在生效期内的 active 词条（国家横切 M4 原子风险不用，留字段）。"""
    rows = (
        await session.scalars(
            select(ComplianceWordlistEntry).where(
                ComplianceWordlistEntry.status == "active",
            )
        )
    ).all()
    out = []
    for e in rows:
        if e.industry is not None and e.industry != industry:
            continue
        if e.effective_from is not None and e.effective_from > now:
            continue
        if e.effective_until is not None and e.effective_until < now:
            continue
        out.append(e)
    return out


def match_words(content: str, entries: Sequence[ComplianceWordlistEntry]) -> list[WordlistHit]:
    """确定性子串匹配（大小写不敏感）。同词命中多条全部返回，定级取最高（Q17）。"""
    haystack = content.casefold()
    return [
        WordlistHit(word=e.word, level=e.level, action=e.action)
        for e in entries
        if e.word and e.word.casefold() in haystack
    ]
