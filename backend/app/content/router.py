"""段12 内容生成端点（P4）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import generation, service
from app.content.schemas import ContentGenerateRequest, ContentProductView
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
