"""段3 灵感库服务：CRUD（Q8 同型，运营可配）＋ DIM-SOURCE 上下文查询。

写口要求内部角色（OPERATIONS 或 PLATFORM_ADMIN），与 fp_source_routes 同档；
读口同样要求内部角色（知识层配置，不外放客户侧）。层语义校验：product 层必须绑定
product_space_id，common 层禁止绑定。
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.rbac import (
    OPERATIONS,
    PLATFORM_ADMIN,
    require_any_role,
)
from app.product.inspiration.models import (
    INSPIRATION_LAYERS,
    LAYER_COMMON,
    LAYER_PRODUCT,
    InspirationEntry,
)

PLATFORM_TENANT = "_platform"


class EntryNotFound(Exception):
    pass


class InvalidInspiration(Exception):
    pass


def _require_writer(actor) -> None:
    require_any_role(actor, OPERATIONS, PLATFORM_ADMIN)


def _validate(layer: str, product_space_id: str | None) -> None:
    if layer not in INSPIRATION_LAYERS:
        raise InvalidInspiration(
            f"layer must be one of {sorted(INSPIRATION_LAYERS)}"
        )
    if layer == LAYER_PRODUCT and not product_space_id:
        raise InvalidInspiration("product layer requires product_space_id")
    if layer == LAYER_COMMON and product_space_id:
        raise InvalidInspiration("common layer must not set product_space_id")


async def list_entries(
    session: AsyncSession,
    *,
    tenant_id: str,
    layer: str | None = None,
    product_space_id: str | None = None,
    enabled: bool | None = None,
) -> Sequence[InspirationEntry]:
    stmt = select(InspirationEntry).where(InspirationEntry.tenant_id == tenant_id)
    if layer is not None:
        stmt = stmt.where(InspirationEntry.layer == layer)
    if product_space_id is not None:
        stmt = stmt.where(InspirationEntry.product_space_id == product_space_id)
    if enabled is not None:
        stmt = stmt.where(InspirationEntry.enabled.is_(enabled))
    return (
        await session.scalars(stmt.order_by(InspirationEntry.created_at))
    ).all()


async def create_entry(
    session: AsyncSession,
    *,
    tenant_id: str,
    layer: str,
    product_space_id: str | None,
    content: str,
    tags: list[str] | None,
    enabled: bool,
    actor,
) -> InspirationEntry:
    _require_writer(actor)
    _validate(layer, product_space_id)
    entry = InspirationEntry(
        tenant_id=tenant_id,
        layer=layer,
        product_space_id=product_space_id,
        content=content,
        tags=list(tags or []),
        enabled=enabled,
        usage_count=0,
    )
    session.add(entry)
    await session.flush()
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="inspiration.create",
        entity_type="inspiration_entry",
        entity_id=entry.entry_id,
        detail={"layer": layer, "product_space_id": product_space_id},
    )
    return entry


async def update_entry(
    session: AsyncSession,
    entry_id: str,
    *,
    content: str | None = None,
    tags: list[str] | None = None,
    enabled: bool | None = None,
    actor,
) -> InspirationEntry:
    _require_writer(actor)
    entry = await session.get(InspirationEntry, entry_id)
    if entry is None:
        raise EntryNotFound(entry_id)
    if content is not None:
        entry.content = content
    if tags is not None:
        entry.tags = list(tags)
    if enabled is not None:
        entry.enabled = enabled
    entry.updated_at = datetime.now(UTC)
    await append_audit(
        session,
        tenant_id=entry.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="inspiration.update",
        entity_type="inspiration_entry",
        entity_id=entry_id,
        detail={
            "content": content is not None,
            "tags": tags is not None,
            "enabled": enabled,
        },
    )
    return entry


async def delete_entry(session: AsyncSession, entry_id: str, actor) -> None:
    _require_writer(actor)
    entry = await session.get(InspirationEntry, entry_id)
    if entry is None:
        raise EntryNotFound(entry_id)
    await session.delete(entry)
    await append_audit(
        session,
        tenant_id=entry.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="inspiration.delete",
        entity_type="inspiration_entry",
        entity_id=entry_id,
    )


async def get_context_for_planning(
    session: AsyncSession, *, tenant_id: str, product_space_id: str
) -> Sequence[InspirationEntry]:
    """DIM-SOURCE 接线：拉取该租户 enabled 的通用层 + 该产品专属层条目作为依据内容。"""
    stmt = (
        select(InspirationEntry)
        .where(
            InspirationEntry.tenant_id == tenant_id,
            InspirationEntry.enabled.is_(True),
        )
        .where(
            or_(
                and_(
                    InspirationEntry.layer == LAYER_COMMON,
                    InspirationEntry.product_space_id.is_(None),
                ),
                InspirationEntry.product_space_id == product_space_id,
            )
        )
        .order_by(InspirationEntry.layer, InspirationEntry.created_at)
    )
    return (await session.scalars(stmt)).all()


def format_inspiration_context(entries: Sequence[InspirationEntry]) -> str:
    """把灵感条目渲染成可注入 DIM-MERGE 提示词的文本块。"""
    if not entries:
        return "（无）"
    lines = []
    for e in entries:
        scope = "通用" if e.layer == LAYER_COMMON else "产品专属"
        tag_part = " #" + " #".join(e.tags) if e.tags else ""
        lines.append(f"- [{scope}] {e.content}{tag_part}")
    return "\n".join(lines)
