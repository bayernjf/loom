"""内容底座 HTTP API（M4/T-M4-02，设计 §4.5）。

前缀 /api/v1/content：提交请求、人审候选、读取候选/列表。
状态机与 skill7 候选同构；错误映射 404/409/422。
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content_base import service
from app.core.content_base.errors import (
    ContentBackendUnavailable,
    ContentBaseError,
    ContentRequestInvalid,
)
from app.core.content_base.models import ContentCandidateRecord
from app.core.content_base.schemas import (
    CandidateStatus,
    ContentCandidateList,
    ContentCandidateView,
    ContentTypeId,
    CreateContentRequest,
    ReviewContentRequest,
)
from app.core.content_base.types import ContentConstraints, ContentRequest
from app.core.db import get_session
from app.core.problem_details import logged_http_error

router = APIRouter(prefix="/api/v1/content", tags=["content-base"])


def _to_domain(body: CreateContentRequest) -> ContentRequest:
    return ContentRequest(
        product_id=body.product_id,
        channel=body.channel,
        content_type=body.content_type,
        inputs=body.inputs,
        constraints=ContentConstraints(
            wordlist=body.constraints.wordlist,
            banned=body.constraints.banned,
            brand=body.constraints.brand,
        ),
        idempotency_key=body.idempotency_key,
        locale=body.locale,
    )


def _view(record: ContentCandidateRecord) -> ContentCandidateView:
    return ContentCandidateView(
        candidate_id=record.candidate_id,
        product_id=record.product_id,
        channel=record.channel,
        content_type=cast(ContentTypeId, record.content_type),
        body=record.body,
        evidence_refs=list(record.evidence_refs),
        status=cast(CandidateStatus, record.status),
        final_body=record.final_body,
        review_note=record.review_note,
        reviewed_by=record.reviewed_by,
        reviewed_at=(record.reviewed_at.isoformat() if record.reviewed_at else None),
        created_at=(record.created_at.isoformat() if record.created_at else None),
    )


@router.post("/requests", response_model=ContentCandidateView, status_code=201)
async def create_request(
    body: CreateContentRequest,
    session: AsyncSession = Depends(get_session),
) -> ContentCandidateView:
    try:
        record = await service.submit_candidate(session, _to_domain(body), actor_id=body.actor.id)
        await session.commit()
    except ContentRequestInvalid as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ContentBackendUnavailable as exc:
        await session.rollback()
        raise logged_http_error(503, "content backend unavailable", exc) from exc
    except ContentBaseError as exc:
        await session.rollback()
        raise logged_http_error(500, "internal error", exc) from exc
    return _view(record)


@router.post("/{candidate_id}/review", response_model=ContentCandidateView)
async def review(
    candidate_id: str,
    body: ReviewContentRequest,
    session: AsyncSession = Depends(get_session),
) -> ContentCandidateView:
    try:
        record = await service.review_candidate(
            session,
            candidate_id,
            body.decision,
            final_body=body.final_body,
            note=body.note,
            reviewer_id=body.actor.id,
        )
        await session.commit()
    except service.CandidateNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="content candidate not found") from exc
    except service.CandidateNotReviewable as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ContentRequestInvalid as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ContentBaseError as exc:
        await session.rollback()
        raise logged_http_error(500, "internal error", exc) from exc
    return _view(record)


@router.get("", response_model=ContentCandidateList)
async def list_candidates(
    status: str | None = None,
    product_id: str | None = None,
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> ContentCandidateList:
    records = await service.list_candidates(
        session,
        status=status,
        product_id=product_id,
        channel=channel,
    )
    return ContentCandidateList(candidates=[_view(r) for r in records])


@router.get("/{candidate_id}", response_model=ContentCandidateView)
async def get_candidate(
    candidate_id: str,
    session: AsyncSession = Depends(get_session),
) -> ContentCandidateView:
    try:
        record = await service.get_candidate(session, candidate_id)
    except service.CandidateNotFound as exc:
        raise HTTPException(status_code=404, detail="content candidate not found") from exc
    return _view(record)
