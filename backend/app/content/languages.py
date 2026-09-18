"""Q119/Q58 段12 内容多语言：语言清单 CRUD + 语言交集求值。

Q58 口径：
- 语言 = 发布位目标市场 ∩ 产品录入的目标市场/语言；
- 每个语言版为独立成品（独立复检 / 独立入成品库 / 独立客户审，由
  content_products 的 (final_id, language, kind) 唯一约束承载）；
- 支持语言清单配置化（content_languages，dictionary_admin 维护）。

发布位目标市场取 FCW.country；产品录入侧目标语言取 ProductSpace.target_languages
（Q119 新增 nullable 列，NULL/空 = 未声明，交集时不做产品侧收窄）。
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import (
    LANGUAGE_ACTIVE,
    LANGUAGE_ARCHIVED,
    ContentLanguage,
)
from app.core.audit import append_audit
from app.core.rbac import DICTIONARY_ADMIN, OPERATIONS, require_any_role
from app.product.product_intake.models import ProductSpace

PLATFORM_TENANT = "_platform"


class LanguageInvalid(Exception):
    pass


class LanguageNotFound(Exception):
    pass


class ProductSpaceNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# 纯函数（单测覆盖，不碰 DB）
# ---------------------------------------------------------------------------

def covers_market(markets: Sequence[str] | None, country: str | None) -> bool:
    """语言 markets 是否覆盖发布位市场。

    空 markets（[]/None）= 适用全部市场（含 country 为空的通用发布位）。
    """
    if not markets:
        return True
    return country is not None and country in markets


def eligible_codes(
    catalog: Sequence[tuple[str, Sequence[str] | None]],
    country: str | None,
    ps_target_languages: Sequence[str] | None,
) -> list[str]:
    """求可生成语言（保持清单 code 顺序）。

    catalog：active 语言的 (code, markets) 序列；
    产品侧 ps_target_languages 为 NULL/空 = 未声明、不收窄。
    """
    from_catalog = [
        code for code, markets in catalog if covers_market(markets, country)
    ]
    if ps_target_languages:
        wanted = set(ps_target_languages)
        from_catalog = [c for c in from_catalog if c in wanted]
    return from_catalog


# ---------------------------------------------------------------------------
# 语言清单 CRUD（dictionary_admin）
# ---------------------------------------------------------------------------

async def list_languages(
    session: AsyncSession, *, include_archived: bool = False
) -> list[ContentLanguage]:
    stmt = select(ContentLanguage).order_by(ContentLanguage.code)
    if not include_archived:
        stmt = stmt.where(ContentLanguage.status == LANGUAGE_ACTIVE)
    return list((await session.scalars(stmt)).all())


async def upsert_language(session: AsyncSession, body, actor) -> ContentLanguage:
    require_any_role(actor, DICTIONARY_ADMIN)
    code = (body.code or "").strip()
    name = (body.name or "").strip()
    if not code:
        raise LanguageInvalid("language code required")
    if not name:
        raise LanguageInvalid("language name required")
    markets = list(body.markets or [])
    if any(not isinstance(m, str) or not m.strip() for m in markets):
        raise LanguageInvalid("markets must be non-empty country codes")
    markets = [m.strip() for m in markets]

    lang = await session.get(ContentLanguage, code)
    if lang is None:
        lang = ContentLanguage(code=code, name=name, markets=markets)
        session.add(lang)
    else:
        lang.name = name
        lang.markets = markets
    # 显式 upsert 即（重新）启用；与 content_goals.upsert_goal 复活口径一致。
    lang.status = LANGUAGE_ACTIVE
    lang.updated_by = actor.id
    lang.updated_at = _now()
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="content_language.upsert",
        entity_type="content_language",
        entity_id=code,
        detail={"name": name, "markets": markets},
    )
    return lang


async def archive_language(session: AsyncSession, code: str, actor) -> None:
    require_any_role(actor, DICTIONARY_ADMIN)
    lang = await session.get(ContentLanguage, code)
    if lang is None:
        raise LanguageNotFound(code)
    lang.status = LANGUAGE_ARCHIVED
    lang.updated_by = actor.id
    lang.updated_at = _now()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="content_language.archive",
        entity_type="content_language",
        entity_id=code,
    )


# ---------------------------------------------------------------------------
# 语言交集（段12 生成前校验）
# ---------------------------------------------------------------------------

async def active_catalog(
    session: AsyncSession,
) -> list[tuple[str, list[str]]]:
    rows = await list_languages(session)
    return [(lang.code, list(lang.markets or [])) for lang in rows]


async def eligible_for_fcw(
    session: AsyncSession, fcw, product_space: ProductSpace | None = None
) -> list[str]:
    """发布位市场（fcw.country）∩ 产品目标语言（PS.target_languages）。"""
    catalog = await active_catalog(session)
    ps_target = None
    if product_space is not None:
        ps_target = product_space.target_languages
    return eligible_codes(catalog, fcw.country, ps_target)


async def set_ps_target_languages(
    session: AsyncSession, product_space_id: str, languages: Sequence[str], actor
) -> ProductSpace:
    require_any_role(actor, OPERATIONS)
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)
    codes = [c.strip() for c in (languages or []) if isinstance(c, str) and c.strip()]
    if len(set(codes)) != len(codes):
        raise LanguageInvalid("target languages must be unique")
    ps.target_languages = codes or None
    ps.updated_at = _now()
    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="product_space.target_languages.set",
        entity_type="product_space",
        entity_id=product_space_id,
        detail={"target_languages": ps.target_languages},
    )
    return ps
