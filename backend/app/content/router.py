"""段12 内容生成端点（P4）。

P0（2026-10-30）鉴权收口：本路由全部端点都必须携带已验真凭证——

- 客户口（approve/reject/revise/edit_body/list/detail/languages）：客户访问令牌
  （``loom_client_``，见 ``client_auth``），租户作用域端点令牌↔tenant 绑定一致；
- 运营口（generate/regenerate/discard/publish-info/语言写口/目标语言）：staff
  个人令牌硬闸 ``require_internal_actor``（不看全局门控、无令牌一律 401）。

端点正文里的异常原文只进日志，客户端一律收固定泛化 detail（Tier0 评审 H2 收口）。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import generation, service
from app.content import languages as l10n
from app.content.models import ContentLanguage
from app.content.schemas import (
    ContentBodyPatch,
    ContentDecisionRequest,
    ContentDiscardRequest,
    ContentGenerateRequest,
    ContentLanguageView,
    ContentProductListItem,
    ContentProductView,
    ContentPublishInfoRequest,
    LanguageArchiveRequest,
    LanguageUpsertRequest,
    TargetLanguagesRequest,
)
from app.core.actor import Actor
from app.core.client_auth.deps import require_client_actor, require_client_identity
from app.core.db import get_session
from app.core.rbac import (
    DICTIONARY_ADMIN,
    OPERATIONS,
    PLATFORM_ADMIN,
    PermissionDenied,
    require_any_role,
)
from app.core.staff_auth.deps import require_internal_actor
from app.final.final_whitelist.models import FinalContentWhitelist
from app.final.final_whitelist.service import FcwRevoked
from app.product.product_intake.models import ProductSpace

logger = logging.getLogger("loom.content")

router = APIRouter(tags=["content"])


def _query_actor(*roles: str):
    """管理面/业务读口 query actor 闸（Q109/Q118 同构：缺 actor_id 422、越权 403）。

    传多个角色时为"任一即可"（同 Q107 ops-queue：operations | platform_admin）。
    """

    def dependency(
        actor_id: str = Query(...),
        roles_param: list[str] = Query(default_factory=list, alias="roles"),
    ) -> Actor:
        actor = Actor(id=actor_id, roles=roles_param)
        try:
            require_any_role(actor, *roles)
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return actor

    return dependency


require_dict_view = _query_actor(DICTIONARY_ADMIN)
require_ops_view = _query_actor(OPERATIONS)
# Q125/Q107：运营队列读口对 operations 与 platform_admin 同时开放。
require_ops_admin_view = _query_actor(OPERATIONS, PLATFORM_ADMIN)

# P0（2026-10-30）：客户内容口强制客户访问令牌（loom_client_），认证身份携带
# whitelist_owner 角色；请求体自报 actor 不再作为身份，由该依赖返回值覆盖。
require_client = require_client_actor()
# 非租户作用域客户只读目录（语言清单）：任一 active 客户令牌即可，不绑租户。
require_client_any = require_client_identity()

# P0（2026-10-30）：运营口一律 staff 令牌硬闸（require_internal_actor 不看全局门控、
# 无令牌一律 401），认证身份覆盖请求体自报 actor——「门控关闭时自报 operations」
# 从此不再能触发会花真钱/改数据的运营动作。
require_ops_action = require_internal_actor(OPERATIONS)
require_dict_action = require_internal_actor(DICTIONARY_ADMIN)


def _http_error(status_code: int, detail: str, exc: Exception) -> HTTPException:
    """异常原文只进日志，客户端收固定泛化 detail（Tier0 评审 H2 收口，仅本路由）。"""
    logger.warning(
        "content endpoint rejected: %s: %s", type(exc).__name__, exc
    )
    return HTTPException(status_code=status_code, detail=detail)


def _language_view(lang: ContentLanguage) -> ContentLanguageView:
    return ContentLanguageView(
        code=lang.code, name=lang.name, markets=list(lang.markets or []), status=lang.status
    )


@router.post(
    "/api/content/generate", response_model=ContentProductView, status_code=201
)
async def generate_content(
    body: ContentGenerateRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_ops_action),
) -> ContentProductView:
    """operations 触发生成（P0：staff 令牌硬闸，认证身份覆盖自报 actor）。"""
    body.actor = actor
    try:
        content = await service.generate_content(session, body)
    except PermissionDenied as exc:
        raise _http_error(403, "operations role required", exc) from exc
    except service.ContentFcwNotFound as exc:
        raise _http_error(404, "final content whitelist not found", exc) from exc
    except FcwRevoked as exc:
        raise _http_error(409, "final content whitelist revoked", exc) from exc
    except service.ContentKindNotImplemented as exc:
        raise _http_error(422, "content kind not implemented", exc) from exc
    except service.ContentLanguageNotEligible as exc:
        raise _http_error(422, "language not eligible for this final", exc) from exc
    except service.ContentDuplicateLanguage as exc:
        raise _http_error(
            409, "content already exists for this final, language and kind", exc
        ) from exc
    except generation.ArticleGenFcwNotFound as exc:
        raise _http_error(404, "final content whitelist not found", exc) from exc
    except generation.ArticleGenState as exc:
        raise _http_error(409, "content state does not allow generation", exc) from exc
    except generation.ArticleGenOutputInvalid as exc:
        raise _http_error(
            502, "content generation returned invalid output", exc
        ) from exc
    except generation.VideoGenFcwNotFound as exc:
        raise _http_error(404, "final content whitelist not found", exc) from exc
    except generation.VideoGenState as exc:
        raise _http_error(409, "content state does not allow generation", exc) from exc
    except generation.VideoGenOutputInvalid as exc:
        raise _http_error(
            502, "content generation returned invalid output", exc
        ) from exc
    await session.commit()
    return service.content_view(content)


@router.post(
    "/api/content/{content_id}/approve", response_model=ContentProductView
)
async def approve_content(
    content_id: str,
    tenant_id: str = Query(min_length=1),
    body: ContentDecisionRequest = ...,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_client),
) -> ContentProductView:
    """Q59 客户审阅通过（P0：客户令牌验真；tenant_id 归属不符统一 404）。"""
    try:
        content = await service.approve_content(
            session, content_id, tenant_id, actor
        )
    except service.ContentNotFound as exc:
        raise _http_error(404, "content not found", exc) from exc
    except ValueError as exc:
        raise _http_error(
            409, "content state does not allow this operation", exc
        ) from exc
    await session.commit()
    return service.content_view(content)


@router.post("/api/content/{content_id}/reject", response_model=ContentProductView)
async def reject_content(
    content_id: str,
    tenant_id: str = Query(min_length=1),
    body: ContentDecisionRequest = ...,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_client),
) -> ContentProductView:
    """Q59 客户驳回（P0：客户令牌验真；tenant_id 归属不符统一 404）。"""
    try:
        content = await service.reject_content(
            session, content_id, tenant_id, body.reason, actor
        )
    except service.ContentNotFound as exc:
        raise _http_error(404, "content not found", exc) from exc
    except service.ContentRejectReasonRequired as exc:
        raise _http_error(422, "reject requires a non-empty reason", exc) from exc
    except ValueError as exc:
        raise _http_error(
            409, "content state does not allow this operation", exc
        ) from exc
    await session.commit()
    return service.content_view(content)


@router.post("/api/content/{content_id}/revise", response_model=ContentProductView)
async def revise_content(
    content_id: str,
    tenant_id: str = Query(min_length=1),
    body: ContentDecisionRequest = ...,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_client),
) -> ContentProductView:
    """Q59 客户改稿（P0：客户令牌验真；tenant_id 归属不符统一 404）。"""
    try:
        content = await service.revise_content(
            session, content_id, tenant_id, actor
        )
    except service.ContentNotFound as exc:
        raise _http_error(404, "content not found", exc) from exc
    except service.ContentReviseCap as exc:
        raise _http_error(
            422, "regenerate cap reached; reject or escalate to manual", exc
        ) from exc
    except ValueError as exc:
        raise _http_error(
            409, "content state does not allow this operation", exc
        ) from exc
    await session.commit()
    return service.content_view(content)


@router.post(
    "/api/content/{content_id}/regenerate", response_model=ContentProductView
)
async def regenerate_content(
    content_id: str,
    body: ContentDecisionRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_ops_action),
) -> ContentProductView:
    """operations 改稿重生成（P0：staff 令牌硬闸，认证身份覆盖自报 actor）。"""
    try:
        content = await service.regenerate_content(session, content_id, actor)
    except PermissionDenied as exc:
        raise _http_error(403, "operations role required", exc) from exc
    except service.ContentNotFound as exc:
        raise _http_error(404, "content not found", exc) from exc
    except service.ContentReviseCap as exc:
        raise _http_error(
            422, "regeneration only allowed in revising state", exc
        ) from exc
    except generation.ArticleGenOutputInvalid as exc:
        raise _http_error(
            502, "content generation returned invalid output", exc
        ) from exc
    except generation.VideoGenFcwNotFound as exc:
        raise _http_error(404, "final content whitelist not found", exc) from exc
    except generation.VideoGenState as exc:
        raise _http_error(409, "content state does not allow generation", exc) from exc
    except generation.VideoGenOutputInvalid as exc:
        raise _http_error(
            502, "content generation returned invalid output", exc
        ) from exc
    await session.commit()
    return service.content_view(content)


@router.post(
    "/api/content/{content_id}/discard", response_model=ContentProductView
)
async def discard_content(
    content_id: str,
    body: ContentDiscardRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_ops_action),
) -> ContentProductView:
    """Q56-b/Q124：运营作废骨架回池（P0：staff 令牌硬闸，难产原因必填）。"""
    try:
        content = await service.discard_content(
            session, content_id, body.reason, actor
        )
    except PermissionDenied as exc:
        await session.rollback()
        raise _http_error(403, "operations role required", exc) from exc
    except service.ContentNotFound as exc:
        await session.rollback()
        raise _http_error(404, "content not found", exc) from exc
    except service.ContentNotDiscardable as exc:
        await session.rollback()
        raise _http_error(409, "content state does not allow discard", exc) from exc
    except service.ContentDiscardReasonRequired as exc:
        await session.rollback()
        raise _http_error(422, "discard requires a non-empty reason", exc) from exc
    await session.commit()
    return service.content_view(content)


# ---- Q125/Q60c：运营待发布队列 + 发布链接/ID 回填 ----
# 静态 GET 路径注册在含 {content_id} 的参数路径之前（同前缀匹配顺序纪律）。


@router.get(
    "/api/admin/content/ready-to-publish",
    response_model=list[ContentProductListItem],
)
async def list_ready_to_publish(
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_ops_admin_view),
) -> list[ContentProductListItem]:
    """运营待发布队列：跨租户仅 ready_for_publish 且未回填，先到先发。"""
    rows = await service.list_ready_to_publish(session, actor)
    return [service.content_list_item(row) for row in rows]


@router.get(
    "/api/admin/content/needs-attention",
    response_model=list[ContentProductListItem],
)
async def list_needs_attention(
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_ops_admin_view),
) -> list[ContentProductListItem]:
    """Q124 运营待处置队列：跨租户 review/revising/rejected，供作废回池操作。"""
    rows = await service.list_needs_attention(session, actor)
    return [service.content_list_item(row) for row in rows]


@router.get(
    "/api/admin/content/{content_id}",
    response_model=ContentProductView,
)
async def admin_get_content(
    content_id: str,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_ops_admin_view),
) -> ContentProductView:
    """Q326：运营跨租户成品详情（只读）。

    内容运营台是跨租户管理页（video-studio 生成结果区在岛内展开）；客户口
    ``GET /api/content/{id}`` 强制 tenant_id 归属校验，管理端不得复用，否则非
    当前占位租户的成品详情一律 404。本口走运营读闸、不做租户过滤
    （``service.get_content`` 不传 tenant_id 即跨租户口径）。注册在
    ready-to-publish / needs-attention 两个静态 GET 之后，避免参数路径吞静态段。
    """
    try:
        content = await service.get_content(session, content_id)
    except service.ContentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return service.content_view(content)


@router.get("/api/admin/content/{content_id}/script-recheck")
async def admin_script_recheck(
    content_id: str,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_ops_admin_view),
) -> dict:
    """Q328（D2 甲）：video-studio 内容清洗区——FCW 表达层脚本文本只读 CCR 复检。

    跨租户只读（同 Q326 管理端成品详情口），不写报告不改文本；未发证成品/
    无表达层文本返回 text_present=false＋detail，不 404（复检对象不存在≠资源不存在）。
    """
    try:
        return await service.script_recheck(session, content_id)
    except service.ContentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/api/admin/content/{content_id}/publish-info",
    response_model=ContentProductView,
)
async def set_publish_info(
    content_id: str,
    body: ContentPublishInfoRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_ops_action),
) -> ContentProductView:
    """Q60c/Q125：运营用托管账号发布后回填平台链接/ID（P0：staff 令牌硬闸）。"""
    try:
        content = await service.set_publish_info(
            session, content_id, body.url, body.platform_post_id, actor
        )
    except PermissionDenied as exc:
        await session.rollback()
        raise _http_error(403, "operations role required", exc) from exc
    except service.ContentNotFound as exc:
        await session.rollback()
        raise _http_error(404, "content not found", exc) from exc
    except service.ContentNotPublishable as exc:
        await session.rollback()
        raise _http_error(
            409, "publish info only accepted for ready-to-publish content", exc
        ) from exc
    except service.ContentPublishUrlRequired as exc:
        await session.rollback()
        raise _http_error(422, "publish url must not be empty", exc) from exc
    await session.commit()
    return service.content_view(content)


# ---- Q119/Q58 多语言：语言清单 + 语言交集 + 产品目标语言 ----


@router.get("/api/admin/content-languages", response_model=list[ContentLanguageView])
async def list_languages(
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_dict_view),
) -> list[ContentLanguageView]:
    rows = await l10n.list_languages(session, include_archived=include_archived)
    return [_language_view(row) for row in rows]


@router.put("/api/admin/content-languages", response_model=ContentLanguageView)
async def upsert_language(
    body: LanguageUpsertRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_dict_action),
) -> ContentLanguageView:
    """语言条目写口（P0：staff 令牌硬闸，dictionary_admin）。"""
    try:
        lang = await l10n.upsert_language(session, body, actor)
        await session.commit()
    except PermissionDenied as exc:
        await session.rollback()
        raise _http_error(403, "dictionary admin role required", exc) from exc
    except l10n.LanguageInvalid as exc:
        await session.rollback()
        raise _http_error(422, "invalid content language", exc) from exc
    return _language_view(lang)


@router.post("/api/admin/content-languages/{code}/archive")
async def archive_language(
    code: str,
    body: LanguageArchiveRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_dict_action),
) -> dict:
    """语言归档写口（P0：staff 令牌硬闸，dictionary_admin）。"""
    try:
        await l10n.archive_language(session, code, actor)
        await session.commit()
    except PermissionDenied as exc:
        await session.rollback()
        raise _http_error(403, "dictionary admin role required", exc) from exc
    except l10n.LanguageNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="content language not found") from exc
    return {"code": code, "status": "archived"}


@router.get("/api/content/eligible-languages")
async def eligible_languages(
    final_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_ops_view),
) -> dict:
    """生成前查询：发布位市场 ∩ 产品目标语言 的可生成语言（Q58）。"""
    fcw = await session.get(FinalContentWhitelist, final_id)
    if fcw is None:
        raise HTTPException(status_code=404, detail=f"FCW {final_id} not found")
    ps = await session.get(ProductSpace, fcw.product_space_id)
    eligible = await l10n.eligible_for_fcw(session, fcw, ps)
    return {
        "final_id": final_id,
        "country": fcw.country,
        "ps_target_languages": ps.target_languages if ps is not None else None,
        "eligible": eligible,
    }


@router.put("/api/product-spaces/{product_space_id}/target-languages")
async def set_target_languages(
    product_space_id: str,
    body: TargetLanguagesRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_ops_action),
) -> dict:
    """产品目标语言写口（P0：staff 令牌硬闸，operations）。"""
    try:
        ps = await l10n.set_ps_target_languages(
            session, product_space_id, body.languages, actor
        )
        await session.commit()
    except PermissionDenied as exc:
        await session.rollback()
        raise _http_error(403, "operations role required", exc) from exc
    except l10n.ProductSpaceNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="product space not found") from exc
    except l10n.LanguageInvalid as exc:
        await session.rollback()
        raise _http_error(422, "invalid content language", exc) from exc
    return {
        "product_space_id": product_space_id,
        "target_languages": ps.target_languages,
    }


# ---- Q122：客户内容页只读列表/详情 + Q56-a 客户人工编辑 ----
# 注意：含 {content_id} 路径参数的 GET 必须注册在 /api/content/eligible-languages
# 等静态路径之后（FastAPI 按注册顺序匹配），故本段置于文件末尾。


@router.get("/api/content", response_model=list[ContentProductListItem])
async def list_content(
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_client),
) -> list[ContentProductListItem]:
    """Q122 客户内容页租户只读列表（P0：客户令牌验真，令牌↔tenant 绑定一致）。"""
    rows = await service.list_content(session, tenant_id)
    return [service.content_list_item(row) for row in rows]


@router.get(
    "/api/content/languages", response_model=list[ContentLanguageView]
)
async def list_active_languages(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_client_any),
) -> list[ContentLanguageView]:
    """B3/Q122：客户录入页目标语言控件的只读清单（仅 active；P0：客户令牌验真，
    非租户作用域故任一 active 客户令牌即可；管理面含归档清单走
    /api/admin/content-languages + dictionary_admin 闸）。

    必须注册在 ``/api/content/{content_id}`` 之前，否则被路径参数吞掉。
    """
    rows = await l10n.list_languages(session)
    return [_language_view(row) for row in rows]


@router.get("/api/content/{content_id}", response_model=ContentProductView)
async def get_content(
    content_id: str,
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_client),
) -> ContentProductView:
    """Q122 客户内容详情（P0：客户令牌验真；归属不符统一 404）。"""
    try:
        content = await service.get_content(session, content_id, tenant_id)
    except service.ContentNotFound as exc:
        raise _http_error(404, "content not found", exc) from exc
    return service.content_view(content)


@router.patch(
    "/api/content/{content_id}/body", response_model=ContentProductView
)
async def edit_content_body(
    content_id: str,
    tenant_id: str = Query(min_length=1),
    body: ContentBodyPatch = ...,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_client),
) -> ContentProductView:
    """Q56-a/Q122：客户在 revising 态人工编辑正文，提交后重过复检回 review
    （P0：客户令牌验真；归属不符统一 404）。"""
    try:
        content = await service.edit_content_body(
            session, content_id, tenant_id, body.body, actor
        )
    except service.ContentNotFound as exc:
        await session.rollback()
        raise _http_error(404, "content not found", exc) from exc
    except service.ContentNotEditable as exc:
        await session.rollback()
        raise _http_error(409, "content is not in an editable state", exc) from exc
    except service.ContentBodyRequired as exc:
        await session.rollback()
        raise _http_error(422, "edited body must not be empty", exc) from exc
    await session.commit()
    return service.content_view(content)
