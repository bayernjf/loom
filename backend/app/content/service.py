"""段12 内容生成服务（P4）。"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.content import generation
from app.content import statemachine as sm
from app.content.models import (
    CONTENT_DRAFT,
    KIND_ARTICLE,
    KIND_VIDEO,
    ContentProduct,
)
from app.content.schemas import ContentGenerateRequest, ContentProductView
from app.core.rbac import OPERATIONS, require_any_role
from app.final.final_whitelist.models import FinalContentWhitelist


class ContentFcwNotFound(Exception):
    pass


class ContentKindNotImplemented(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def content_view(content: ContentProduct) -> ContentProductView:
    return ContentProductView(
        content_id=content.content_id,
        tenant_id=content.tenant_id,
        product_space_id=content.product_space_id,
        final_id=content.final_id,
        goal=content.goal,
        platform=content.platform,
        slot_id=content.slot_id,
        country=content.country,
        kind=content.kind,
        language=content.language,
        body=content.body,
        review_hits=content.review_hits,
        status=content.status,
        reject_reason=content.reject_reason,
        regenerate_count=content.regenerate_count,
        created_at=content.created_at,
    )


async def generate_content(
    session: AsyncSession, body: ContentGenerateRequest
) -> ContentProduct:
    """operations 触发生成：建成品（draft）→ 生成（generating）→ 待客户审阅（review）。"""
    require_any_role(body.actor, OPERATIONS)
    if body.kind == KIND_VIDEO:
        raise ContentKindNotImplemented("video generation deferred to a later P4 slice")
    if body.kind != KIND_ARTICLE:
        raise ContentKindNotImplemented(f"unknown kind {body.kind!r}")

    fcw = await session.get(FinalContentWhitelist, body.final_id)
    if fcw is None:
        raise ContentFcwNotFound(body.final_id)

    content = ContentProduct(
        tenant_id=fcw.tenant_id,
        product_space_id=fcw.product_space_id,
        final_id=fcw.final_id,
        goal=fcw.goal,
        platform=fcw.platform,
        slot_id=fcw.slot_id,
        country=fcw.country,
        kind=body.kind,
        language=body.language,
        status=CONTENT_DRAFT,
        created_by=body.actor.id,
    )
    session.add(content)
    await session.flush()

    content.status = sm.target_status(content.status, sm.EVENT_GENERATE)
    await generation.invoke_article_gen(session, content, body.actor)
    content.status = sm.target_status(content.status, sm.EVENT_COMPLETE)
    content.updated_at = _now()
    return content
