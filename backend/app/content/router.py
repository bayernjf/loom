"""段12 内容生成端点（P4）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import generation, service
from app.content import languages as l10n
from app.content.models import ContentLanguage
from app.content.schemas import (
    ContentDecisionRequest,
    ContentGenerateRequest,
    ContentLanguageView,
    ContentProductView,
    LanguageArchiveRequest,
    LanguageUpsertRequest,
    TargetLanguagesRequest,
)
from app.core.actor import Actor
from app.core.db import get_session
from app.core.rbac import (
    DICTIONARY_ADMIN,
    OPERATIONS,
    PermissionDenied,
    require_any_role,
)
from app.final.final_whitelist.models import FinalContentWhitelist
from app.product.product_intake.models import ProductSpace

router = APIRouter(tags=["content"])


def _query_actor(role: str):
    """管理面/业务读口 query actor 闸（Q109/Q118 同构：缺 actor_id 422、越权 403）。"""

    def dependency(
        actor_id: str = Query(...),
        roles: list[str] = Query(default_factory=list),
    ) -> Actor:
        actor = Actor(id=actor_id, roles=roles)
        try:
            require_any_role(actor, role)
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return actor

    return dependency


require_dict_view = _query_actor(DICTIONARY_ADMIN)
require_ops_view = _query_actor(OPERATIONS)


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
    body: ContentDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> ContentProductView:
    try:
        content = await service.approve_content(session, content_id, body.actor)
    except service.ContentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return service.content_view(content)


@router.post("/api/content/{content_id}/reject", response_model=ContentProductView)
async def reject_content(
    content_id: str,
    body: ContentDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> ContentProductView:
    try:
        content = await service.reject_content(
            session, content_id, body.reason, body.actor
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
    body: ContentDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> ContentProductView:
    try:
        content = await service.revise_content(session, content_id, body.actor)
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
