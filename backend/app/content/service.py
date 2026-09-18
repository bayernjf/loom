"""段12 内容生成 + 复检 + 客户审阅服务（P4）。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import generation
from app.content import languages as l10n
from app.content import statemachine as sm
from app.content.models import (
    CONTENT_DRAFT,
    DEFAULT_LANGUAGE,
    KIND_ARTICLE,
    KIND_VIDEO,
    ContentProduct,
)
from app.content.schemas import ContentGenerateRequest, ContentProductView
from app.core.compliance_wordlist import service as wl_service
from app.core.rbac import OPERATIONS, require_any_role
from app.decision.compliance_center import ccr_rules
from app.final.final_whitelist.models import FinalContentWhitelist
from app.product.product_intake.models import ProductSpace


class ContentFcwNotFound(Exception):
    pass


class ContentKindNotImplemented(Exception):
    pass


class ContentNotFound(Exception):
    pass


class ContentRejectReasonRequired(Exception):
    pass


class ContentReviseCap(Exception):
    pass


class ContentLanguageNotEligible(Exception):
    """Q119/Q58：请求语言不在「发布位市场 ∩ 产品目标语言」交集内。"""


class ContentDuplicateLanguage(Exception):
    """Q119/Q58：同 final_id + language + kind 成品已存在（每语言独立唯一成品）。"""


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


async def _get_content(session: AsyncSession, content_id: str) -> ContentProduct:
    content = await session.get(ContentProduct, content_id)
    if content is None:
        raise ContentNotFound(content_id)
    return content


async def run_content_review(session: AsyncSession, content: ContentProduct) -> dict:
    """段12 复检第 1 项：词库扫描（复用 Q48 词库 + ccr_rules 三层裁决）。

    其余三项（语义级检测 / 施工指令核对 / 国家规则核对）原文未给实现口径，
    P4 第一片占位【待补】。
    """
    ps = await session.get(ProductSpace, content.product_space_id)
    industry = ps.industry_tag if ps is not None else None
    entries = [
        e
        for e in await wl_service.active_entries(session, industry=industry, now=_now())
        if ccr_rules.applicable_to_market(e, content.country)
    ]
    result = ccr_rules.evaluate(entries, content.body or "")
    return {
        "bans": result["bans"],
        "downgrades": result["downgrades"],
        "block_required": result["block_required"],
    }


async def _run_generation(
    session: AsyncSession, content: ContentProduct, actor
) -> ContentProduct:
    """generating 态：调 ARTICLE-GEN 写 body → 复检 → review。"""
    await generation.invoke_article_gen(session, content, actor)
    content.review_hits = await run_content_review(session, content)
    content.status = sm.target_status(content.status, sm.EVENT_COMPLETE)
    content.updated_at = _now()
    return content


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

    # Q119/Q58：语言 = 发布位目标市场（fcw.country）∩ 产品目标语言（PS.target_languages）。
    language = body.language or DEFAULT_LANGUAGE
    ps = await session.get(ProductSpace, fcw.product_space_id)
    eligible = await l10n.eligible_for_fcw(session, fcw, ps)
    if language not in eligible:
        raise ContentLanguageNotEligible(
            f"language {language!r} not eligible for final_id {body.final_id}; "
            f"eligible={eligible}"
        )
    duplicate_id = await session.scalar(
        select(ContentProduct.content_id).where(
            ContentProduct.final_id == body.final_id,
            ContentProduct.language == language,
            ContentProduct.kind == body.kind,
        )
    )
    if duplicate_id is not None:
        raise ContentDuplicateLanguage(
            f"{body.kind} content for {body.final_id} in {language} already exists "
            f"({duplicate_id}); revise/regenerate instead of recreating"
        )

    content = ContentProduct(
        tenant_id=fcw.tenant_id,
        product_space_id=fcw.product_space_id,
        final_id=fcw.final_id,
        goal=fcw.goal,
        platform=fcw.platform,
        slot_id=fcw.slot_id,
        country=fcw.country,
        kind=body.kind,
        language=language,
        status=CONTENT_DRAFT,
        created_by=body.actor.id,
    )
    session.add(content)
    await session.flush()

    content.status = sm.target_status(content.status, sm.EVENT_GENERATE)
    return await _run_generation(session, content, body.actor)


async def approve_content(session: AsyncSession, content_id: str, actor) -> ContentProduct:
    """客户通过（Q59）：review → ready_for_publish。"""
    content = await _get_content(session, content_id)
    content.status = sm.target_status(content.status, sm.EVENT_APPROVE)
    content.updated_at = _now()
    return content


async def reject_content(
    session: AsyncSession, content_id: str, reason: str | None, actor
) -> ContentProduct:
    """客户驳回（Q59 必选原因）：review → rejected。"""
    content = await _get_content(session, content_id)
    if not reason or not reason.strip():
        raise ContentRejectReasonRequired("reject requires a non-empty reason")
    content.status = sm.target_status(content.status, sm.EVENT_REJECT)
    content.reject_reason = reason
    content.updated_at = _now()
    return content


async def revise_content(session: AsyncSession, content_id: str, actor) -> ContentProduct:
    """客户改稿（Q59/Q56）：review → revising；达重生成上限则拒绝。"""
    content = await _get_content(session, content_id)
    if not sm.revise_allowed(content.status, content.regenerate_count):
        raise ContentReviseCap(
            f"regenerate cap {content.regenerate_count}/{sm.MAX_REGENERATE} reached; "
            "reject or escalate to manual"
        )
    content.status = sm.target_status(content.status, sm.EVENT_REVISE)
    content.updated_at = _now()
    return content


async def regenerate_content(
    session: AsyncSession, content_id: str, actor
) -> ContentProduct:
    """operations 改稿重生成（Q56）：revising → generating（count+1）→ review。"""
    require_any_role(actor, OPERATIONS)
    content = await _get_content(session, content_id)
    if content.status != sm.CONTENT_REVISING:
        raise ContentReviseCap(
            f"regenerate only allowed in {sm.CONTENT_REVISING}, current {content.status}"
        )
    content.regenerate_count += 1
    content.status = sm.target_status(content.status, sm.EVENT_GENERATE)
    return await _run_generation(session, content, actor)
