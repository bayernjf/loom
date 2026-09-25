"""段12 内容生成 + 复检 + 客户审阅服务（P4）。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import generation
from app.content import languages as l10n
from app.content import quality as qc
from app.content import semantic as sem
from app.content import statemachine as sm
from app.content.models import (
    CONTENT_DISCARDED,
    CONTENT_DRAFT,
    CONTENT_READY,
    CONTENT_REJECTED,
    CONTENT_REVIEW,
    CONTENT_REVISING,
    DEFAULT_LANGUAGE,
    KIND_ARTICLE,
    KIND_VIDEO,
    ContentProduct,
)
from app.content.schemas import (
    ContentGenerateRequest,
    ContentProductListItem,
    ContentProductView,
)
from app.core.audit import append_audit
from app.core.compliance_wordlist import service as wl_service
from app.core.config_center.knobs import knob
from app.core.rbac import OPERATIONS, PLATFORM_ADMIN, require_any_role
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


class ContentBodyRequired(Exception):
    """Q56-a/Q122：人工编辑提交的正文为空白。"""


class ContentNotEditable(Exception):
    """Q56-a/Q122：仅 revising 态允许客户人工编辑正文。"""


class ContentDiscardReasonRequired(Exception):
    """Q56-b/Q124：作废骨架回池必须记录难产原因。"""


class ContentNotDiscardable(Exception):
    """Q56-b/Q124：当前状态不允许作废（仅 review/revising/rejected 可作废）。"""


class ContentPublishUrlRequired(Exception):
    """Q60c/Q125：发布回填必须提供非空白平台链接。"""


class ContentNotPublishable(Exception):
    """Q60c/Q125：仅 ready_for_publish 态可回填发布信息。"""


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
        discard_reason=content.discard_reason,
        published_url=content.published_url,
        platform_post_id=content.platform_post_id,
        published_at=content.published_at,
        quality_score=content.quality_score,
        quality_issues=content.quality_issues,
        quality_threshold=float(knob(qc.QUALITY_THRESHOLD_KEY)),
        quality_advisory=qc.quality_advisory_for(
            content.quality_score, float(knob(qc.QUALITY_THRESHOLD_KEY))
        ),
    )


def content_list_item(content: ContentProduct) -> ContentProductListItem:
    """Q122 列表项：详情视图去掉 body（正文仅在详情返回）。"""
    return ContentProductListItem(
        **content_view(content).model_dump(exclude={"body"})
    )


async def _get_content(
    session: AsyncSession, content_id: str, tenant_id: str | None = None
) -> ContentProduct:
    """Q200 #32：按 id 定位并按声明租户反查归属。

    客户口（详情/裁决/正文改写）必须显式声明 tenant_id，归属不符统一
    ContentNotFound（404）——与 #31 导出口口径一致：不提供存在性探针，
    跨租户与不存在同回 404。运营口（operations 闸、跨租户）不传 tenant_id。
    """
    content = await session.get(ContentProduct, content_id)
    if content is None:
        raise ContentNotFound(content_id)
    if tenant_id is not None and content.tenant_id != tenant_id:
        raise ContentNotFound(content_id)
    return content


async def list_content(
    session: AsyncSession, tenant_id: str
) -> list[ContentProduct]:
    """Q122 客户内容列表：按租户倒序返回全部成品（每语言一条，前端按 final_id 并列）。"""
    stmt = (
        select(ContentProduct)
        .where(ContentProduct.tenant_id == tenant_id)
        .order_by(ContentProduct.created_at.desc(), ContentProduct.content_id.desc())
    )
    return list((await session.scalars(stmt)).all())


async def get_content(
    session: AsyncSession, content_id: str, tenant_id: str | None = None
) -> ContentProduct:
    """Q122 客户内容详情（Q200 #32：按声明租户反查归属，不符 404）。"""
    return await _get_content(session, content_id, tenant_id)


async def run_content_review(session: AsyncSession, content: ContentProduct) -> dict:
    """段12 CONTENT-COMPLIANCE 复检（Q59 四项）。

    - 第 1 项词库扫描：复用 Q48 词库 + ccr_rules 三层裁决，ban 命中
      ``block_required=true`` 为确定性硬阻断；
    - 第 2 项语义级检测（Q121）：模型网关 ARTICLE-SEMANTIC-CHECK 只读检测，
      结果落 ``review_hits["semantic"]``，**纯 advisory**（不阻断 approve、
      不改 block_required）；检测不可用记 checked=false + error，不阻断生成。

    施工指令核对 / 国家规则核对两项原文未给实现口径，仍占位【待补】。
    """
    ps = await session.get(ProductSpace, content.product_space_id)
    industry = ps.industry_tag if ps is not None else None
    entries = [
        e
        for e in await wl_service.active_entries(session, industry=industry, now=_now())
        if ccr_rules.applicable_to_market(e, content.country)
    ]
    result = ccr_rules.evaluate(entries, content.body or "")
    review_hits = {
        "bans": result["bans"],
        "downgrades": result["downgrades"],
        "block_required": result["block_required"],
    }
    review_hits["semantic"] = await sem.run_semantic_check(session, content)
    return review_hits


async def _run_generation(
    session: AsyncSession, content: ContentProduct, actor
) -> ContentProduct:
    """generating 态：调 ARTICLE-GEN 写 body → 复检 → review。"""
    await generation.invoke_article_gen(session, content, actor)
    content.review_hits = await run_content_review(session, content)
    # Q120/Q57：AI 质量分（ARTICLE-QC）辅助参考，advisory 不阻断发证/驳回。
    await qc.invoke_article_qc(session, content)
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
    # Q124/Q56-b：已作废（discarded）行不占唯一键，允许同 final+lang+kind 重新生成
    # （"作废骨架回池"）；与 partial unique index uq_content_final_language_kind 双保险。
    duplicate_id = await session.scalar(
        select(ContentProduct.content_id).where(
            ContentProduct.final_id == body.final_id,
            ContentProduct.language == language,
            ContentProduct.kind == body.kind,
            ContentProduct.status != CONTENT_DISCARDED,
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


async def approve_content(
    session: AsyncSession, content_id: str, tenant_id: str, actor
) -> ContentProduct:
    """客户通过（Q59）：review → ready_for_publish（Q200 #32：按租户归属校验）。"""
    content = await _get_content(session, content_id, tenant_id)
    content.status = sm.target_status(content.status, sm.EVENT_APPROVE)
    content.updated_at = _now()
    return content


async def reject_content(
    session: AsyncSession, content_id: str, tenant_id: str, reason: str | None, actor
) -> ContentProduct:
    """客户驳回（Q59 必选原因）：review → rejected（Q200 #32：按租户归属校验）。"""
    content = await _get_content(session, content_id, tenant_id)
    if not reason or not reason.strip():
        raise ContentRejectReasonRequired("reject requires a non-empty reason")
    content.status = sm.target_status(content.status, sm.EVENT_REJECT)
    content.reject_reason = reason
    content.updated_at = _now()
    return content


async def revise_content(
    session: AsyncSession, content_id: str, tenant_id: str, actor
) -> ContentProduct:
    """客户改稿（Q59/Q56）：review → revising；达重生成上限则拒绝（Q200 #32：按租户归属校验）。"""
    content = await _get_content(session, content_id, tenant_id)
    limit = int(knob(qc.REGEN_LIMIT_KEY))
    if not sm.revise_allowed(content.status, content.regenerate_count, limit):
        raise ContentReviseCap(
            f"regenerate cap {content.regenerate_count}/{limit} reached; "
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


async def edit_content_body(
    session: AsyncSession, content_id: str, tenant_id: str, new_body: str, actor
) -> ContentProduct:
    """Q56-a/Q122 客户人工编辑（revising → review；Q200 #32：按租户归属校验）。

    与 operations regenerate 的区别：不调 ARTICLE-GEN、不增 regenerate_count；
    替换正文后强制重过复检（词库 + 语义，Q59）与 ARTICLE-QC 质量分，再回 review。
    """
    content = await _get_content(session, content_id, tenant_id)
    if content.status != sm.CONTENT_REVISING:
        raise ContentNotEditable(
            f"manual edit only allowed in {sm.CONTENT_REVISING}, "
            f"current {content.status}"
        )
    if not new_body or not new_body.strip():
        raise ContentBodyRequired("edited body must not be empty")
    content.body = new_body
    content.review_hits = await run_content_review(session, content)
    await qc.invoke_article_qc(session, content)
    content.status = sm.target_status(
        content.status, sm.EVENT_MANUAL_RESUBMIT
    )
    content.updated_at = _now()
    await append_audit(
        session,
        tenant_id=content.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="content.body_edited",
        entity_type="content_product",
        entity_id=content.content_id,
        detail={
            "final_id": content.final_id,
            "language": content.language,
            "kind": content.kind,
        },
    )
    return content


async def discard_content(
    session: AsyncSession, content_id: str, reason: str, actor
) -> ContentProduct:
    """Q56-b/Q124 运营作废骨架回池（review|revising|rejected → discarded）。

    作废为终态只读动作：记录难产原因、释放 (final_id, language, kind) 唯一占位
    （partial unique index 排除 discarded，之后可重新生成）。客户无此动作入口。
    """
    require_any_role(actor, OPERATIONS)
    content = await _get_content(session, content_id)
    if not sm.can_transition(content.status, sm.EVENT_DISCARD):
        raise ContentNotDiscardable(
            f"discard only allowed from review/revising/rejected, "
            f"current {content.status}"
        )
    if not reason or not reason.strip():
        raise ContentDiscardReasonRequired("discard requires a non-empty reason")
    content.status = sm.target_status(content.status, sm.EVENT_DISCARD)
    content.discard_reason = reason
    content.updated_at = _now()
    await append_audit(
        session,
        tenant_id=content.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="content.discarded",
        entity_type="content_product",
        entity_id=content.content_id,
        detail={
            "final_id": content.final_id,
            "language": content.language,
            "kind": content.kind,
            "reason": reason,
        },
    )
    return content


DISCARD_RETENTION_KEY = "content.discard_retention_days"
PURGE_ACTION = "content.discard_purged"


async def purge_expired_discarded(
    session: AsyncSession, now: datetime, limit: int
) -> int:
    """Q187/C4：过保留期的 discarded 终态成品物理清理（甲案，门控见 config）。

    只清理**无任何下游引用**的行：effect_records.matched_content_id 与
    effect_claims.content_id 是硬 FK（Q126/Q127），import_jobs.content_id 是
    payload 可重放的作业历史（Q161）——被引用的行本身即归档，一律留档不删，
    既避免 FK 违约也不切断段13 时序。

    保留窗口取配置中心 ``content.discard_retention_days``（热更）；计时基准是
    discard 时写入的 updated_at（表无 discarded_at 列，discarded 为终态故其后
    不再被改写）。逐行写 PURGE_ACTION 审计（actor 为空＝系统作业），提交边界由
    统一 runner 负责，不自行提交。
    """
    from app.core.effects.models import EffectClaim, EffectRecord
    from app.core.imports.models import ImportJob

    cutoff = now - timedelta(days=int(knob(DISCARD_RETENTION_KEY)))
    stmt = (
        select(ContentProduct)
        .where(
            ContentProduct.status == CONTENT_DISCARDED,
            ContentProduct.updated_at.is_not(None),
            ContentProduct.updated_at <= cutoff,
            ~exists(
                select(1).where(
                    EffectRecord.matched_content_id == ContentProduct.content_id
                )
            ),
            ~exists(
                select(1).where(EffectClaim.content_id == ContentProduct.content_id)
            ),
            ~exists(
                select(1).where(ImportJob.content_id == ContentProduct.content_id)
            ),
        )
        .order_by(ContentProduct.updated_at.asc(), ContentProduct.content_id.asc())
        .limit(limit)
    )
    expired = list((await session.scalars(stmt)).all())
    for content in expired:
        tenant_id = content.tenant_id
        content_id = content.content_id
        detail = {
            "final_id": content.final_id,
            "language": content.language,
            "kind": content.kind,
            "discard_reason": content.discard_reason,
            "discarded_at": content.updated_at.isoformat(),
            "retention_days": int(knob(DISCARD_RETENTION_KEY)),
        }
        await session.delete(content)
        await append_audit(
            session,
            tenant_id=tenant_id,
            actor_id=None,
            actor_roles=None,
            action=PURGE_ACTION,
            entity_type="content_product",
            entity_id=content_id,
            detail=detail,
        )
    return len(expired)


async def list_ready_to_publish(
    session: AsyncSession, actor
) -> list[ContentProduct]:
    """Q60c/Q125 运营发布队列：跨租户、全部 ready_for_publish 成品（published_at
    为空=待回填，非空=已回填，前端分区并显链接），按 created_at 升序（先到先发）。
    行正文不在队列返回（列表项序列化排除 body）。
    读口同 Q107 ops-queue 对 operations | platform_admin 开放。
    """
    require_any_role(actor, OPERATIONS, PLATFORM_ADMIN)
    stmt = (
        select(ContentProduct)
        .where(ContentProduct.status == CONTENT_READY)
        .order_by(ContentProduct.created_at.asc(), ContentProduct.content_id.asc())
    )
    return list((await session.scalars(stmt)).all())


# Q124/Q56-b：运营可作废的状态（discard 事件白名单），也是管理端"待处置"队列口径。
DISCARD_CANDIDATE_STATUSES = (CONTENT_REVIEW, CONTENT_REVISING, CONTENT_REJECTED)


async def list_needs_attention(
    session: AsyncSession, actor
) -> list[ContentProduct]:
    """Q124 运营待处置队列：跨租户、状态 ∈ review/revising/rejected（可作废回池），
    按 created_at 升序（先卡住先处置）。行正文不在队列返回。
    读口同 Q107 ops-queue 对 operations | platform_admin 开放。
    """
    require_any_role(actor, OPERATIONS, PLATFORM_ADMIN)
    stmt = (
        select(ContentProduct)
        .where(ContentProduct.status.in_(DISCARD_CANDIDATE_STATUSES))
        .order_by(ContentProduct.created_at.asc(), ContentProduct.content_id.asc())
    )
    return list((await session.scalars(stmt)).all())


async def set_publish_info(
    session: AsyncSession,
    content_id: str,
    url: str,
    platform_post_id: str | None,
    actor,
) -> ContentProduct:
    """Q60c/Q125 运营用托管账号发布后回填平台链接/ID（仅 ready_for_publish）。

    可重复回填以修正链接（url 必填）；published_at 仅首次回填时落时间，
    platform_post_id 缺省（None）表示不动已有值，空串视为清空。
    Agent 抓取 / effect-callback 回流随段 13（V2），本切片不涉及。
    """
    require_any_role(actor, OPERATIONS)
    content = await _get_content(session, content_id)
    if content.status != CONTENT_READY:
        raise ContentNotPublishable(
            f"publish info only accepted in {CONTENT_READY}, "
            f"current {content.status}"
        )
    if not url or not url.strip():
        raise ContentPublishUrlRequired("published url must not be empty")
    content.published_url = url.strip()
    if platform_post_id is not None:
        content.platform_post_id = platform_post_id.strip() or None
    if content.published_at is None:
        content.published_at = _now()
    content.updated_at = _now()
    await append_audit(
        session,
        tenant_id=content.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="content.publish_info_set",
        entity_type="content_product",
        entity_id=content.content_id,
        detail={
            "final_id": content.final_id,
            "language": content.language,
            "kind": content.kind,
            "url": content.published_url,
            "platform_post_id": content.platform_post_id,
        },
    )
    return content
