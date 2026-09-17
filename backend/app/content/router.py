"""段12 内容生成端点（P4）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import generation, service
from app.content.schemas import (
    ContentDecisionRequest,
    ContentGenerateRequest,
    ContentProductView,
)
from app.core.db import get_session
from app.core.rbac import PermissionDenied

router = APIRouter(tags=["content"])


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
