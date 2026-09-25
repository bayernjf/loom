"""段12 内容生成端点（P4）。"""

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
from app.core.db import get_session
from app.core.rbac import (
    DICTIONARY_ADMIN,
    OPERATIONS,
    PLATFORM_ADMIN,
    PermissionDenied,
    require_any_role,
)
from app.final.final_whitelist.models import FinalContentWhitelist
from app.product.product_intake.models import ProductSpace

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
) -> ContentProductView:
    try:
        content = await service.generate_content(session, body)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ContentFcwNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ContentKindNotImplemented as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.ContentLanguageNotEligible as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.ContentDuplicateLanguage as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except generation.ArticleGenFcwNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except generation.ArticleGenState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except generation.ArticleGenOutputInvalid as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
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
) -> ContentProductView:
    """Q59 客户审阅通过（Q200 #32：必填 tenant_id，归属不符统一 404）。"""
    try:
        content = await service.approve_content(
            session, content_id, tenant_id, body.actor
        )
    except service.ContentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return service.content_view(content)


@router.post("/api/content/{content_id}/reject", response_model=ContentProductView)
async def reject_content(
    content_id: str,
    tenant_id: str = Query(min_length=1),
    body: ContentDecisionRequest = ...,
    session: AsyncSession = Depends(get_session),
) -> ContentProductView:
    """Q59 客户驳回（Q200 #32：必填 tenant_id，归属不符统一 404）。"""
    try:
        content = await service.reject_content(
            session, content_id, tenant_id, body.reason, body.actor
        )
    except service.ContentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ContentRejectReasonRequired as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return service.content_view(content)


@router.post("/api/content/{content_id}/revise", response_model=ContentProductView)
async def revise_content(
    content_id: str,
    tenant_id: str = Query(min_length=1),
    body: ContentDecisionRequest = ...,
    session: AsyncSession = Depends(get_session),
) -> ContentProductView:
    """Q59 客户改稿（Q200 #32：必填 tenant_id，归属不符统一 404）。"""
    try:
        content = await service.revise_content(
            session, content_id, tenant_id, body.actor
        )
    except service.ContentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ContentReviseCap as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return service.content_view(content)


@router.post(
    "/api/content/{content_id}/regenerate", response_model=ContentProductView
)
async def regenerate_content(
    content_id: str,
    body: ContentDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> ContentProductView:
    try:
        content = await service.regenerate_content(session, content_id, body.actor)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ContentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ContentReviseCap as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except generation.ArticleGenOutputInvalid as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await session.commit()
    return service.content_view(content)


@router.post(
    "/api/content/{content_id}/discard", response_model=ContentProductView
)
async def discard_content(
    content_id: str,
    body: ContentDiscardRequest,
    session: AsyncSession = Depends(get_session),
) -> ContentProductView:
    """Q56-b/Q124：运营作废骨架回池（operations 闸，难产原因必填）。"""
    try:
        content = await service.discard_content(
            session, content_id, body.reason, body.actor
        )
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ContentNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ContentNotDiscardable as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.ContentDiscardReasonRequired as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@router.put(
    "/api/admin/content/{content_id}/publish-info",
    response_model=ContentProductView,
)
async def set_publish_info(
    content_id: str,
    body: ContentPublishInfoRequest,
    session: AsyncSession = Depends(get_session),
) -> ContentProductView:
    """Q60c/Q125：运营用托管账号发布后回填平台链接/ID（operations 闸）。"""
    try:
        content = await service.set_publish_info(
            session, content_id, body.url, body.platform_post_id, body.actor
        )
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ContentNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ContentNotPublishable as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.ContentPublishUrlRequired as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
) -> ContentLanguageView:
    try:
        lang = await l10n.upsert_language(session, body, body.actor)
        await session.commit()
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except l10n.LanguageInvalid as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _language_view(lang)


@router.post("/api/admin/content-languages/{code}/archive")
async def archive_language(
    code: str,
    body: LanguageArchiveRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        await l10n.archive_language(session, code, body.actor)
        await session.commit()
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
) -> dict:
    try:
        ps = await l10n.set_ps_target_languages(
            session, product_space_id, body.languages, body.actor
        )
        await session.commit()
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except l10n.ProductSpaceNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="product space not found") from exc
    except l10n.LanguageInvalid as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
) -> list[ContentProductListItem]:
    # Q122：客户内容页租户只读列表（口径同 Q101 compliance/overview：
    # 无 query actor 闸，未知租户 200 返回空列表，不写审计）。
    rows = await service.list_content(session, tenant_id)
    return [service.content_list_item(row) for row in rows]


@router.get(
    "/api/content/languages", response_model=list[ContentLanguageView]
)
async def list_active_languages(
    session: AsyncSession = Depends(get_session),
) -> list[ContentLanguageView]:
    """B3/Q122：客户录入页目标语言控件的只读清单（仅 active，无闸；
    管理面含归档清单走 /api/admin/content-languages + dictionary_admin 闸）。

    必须注册在 ``/api/content/{content_id}`` 之前，否则被路径参数吞掉。
    """
    rows = await l10n.list_languages(session)
    return [_language_view(row) for row in rows]


@router.get("/api/content/{content_id}", response_model=ContentProductView)
async def get_content(
    content_id: str,
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
) -> ContentProductView:
    """Q122 客户内容详情（Q200 #32：必填 tenant_id，归属不符统一 404）。"""
    try:
        content = await service.get_content(session, content_id, tenant_id)
    except service.ContentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return service.content_view(content)


@router.patch(
    "/api/content/{content_id}/body", response_model=ContentProductView
)
async def edit_content_body(
    content_id: str,
    tenant_id: str = Query(min_length=1),
    body: ContentBodyPatch = ...,
    session: AsyncSession = Depends(get_session),
) -> ContentProductView:
    """Q56-a/Q122：客户在 revising 态人工编辑正文，提交后重过复检回 review
    （Q200 #32：必填 tenant_id，归属不符统一 404）。"""
    try:
        content = await service.edit_content_body(
            session, content_id, tenant_id, body.body, body.actor
        )
    except service.ContentNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ContentNotEditable as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.ContentBodyRequired as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return service.content_view(content)
