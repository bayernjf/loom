"""内容底座 HTTP API Pydantic 契约（M4/T-M4-02，设计 §4.5）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.actor import Actor

ContentTypeId = Literal["detail", "post", "short_video_script", "qa"]
ReviewDecisionId = Literal["confirmed", "modified", "rejected"]
CandidateStatus = Literal["pending_review", "confirmed", "modified", "rejected"]


class ContentConstraintsModel(BaseModel):
    wordlist: list[str] = Field(default_factory=list)
    banned: list[str] = Field(default_factory=list)
    brand: list[str] = Field(default_factory=list)


class CreateContentRequest(BaseModel):
    """POST /api/v1/content/requests。"""

    product_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    content_type: ContentTypeId
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: ContentConstraintsModel = Field(default_factory=ContentConstraintsModel)
    idempotency_key: str | None = Field(default=None, min_length=1)
    actor: Actor


class ReviewContentRequest(BaseModel):
    """POST /api/v1/content/{candidate_id}/review。"""

    decision: ReviewDecisionId
    final_body: dict[str, Any] | None = None
    note: str | None = None
    actor: Actor


class ContentCandidateView(BaseModel):
    candidate_id: str
    product_id: str
    channel: str
    content_type: ContentTypeId
    body: dict[str, Any]
    evidence_refs: list[str]
    status: CandidateStatus
    final_body: dict[str, Any] | None = None
    review_note: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    created_at: str | None = None


class ContentCandidateList(BaseModel):
    candidates: list[ContentCandidateView]
