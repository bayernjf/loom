"""内存内容后端（M4/T-M4-01）：参考实现，完整状态流转。

不触网、不调模型：submit 时由 assembly 确定性组装候选 body，
使契约在没有模型 key 时也可验证。重启即丢，生产用持久后端。
"""

from __future__ import annotations

from typing import Any

from app.core.content_base import assembly
from app.core.content_base.base import ContentBackend
from app.core.content_base.errors import (
    ContentCandidateNotFound,
    ContentCandidateNotReviewable,
    ContentRequestInvalid,
)
from app.core.content_base.types import (
    ContentCandidate,
    ContentRequest,
    ReviewDecisionId,
    new_candidate_id,
    now_utc,
)


class InMemoryContentBackend(ContentBackend):
    def __init__(self) -> None:
        self._candidates: dict[str, ContentCandidate] = {}
        # idempotency_key -> candidate_id
        self._idempotency: dict[str, str] = {}

    async def submit(self, request: ContentRequest) -> ContentCandidate:
        if request.idempotency_key is not None:
            existing_id = self._idempotency.get(request.idempotency_key)
            if existing_id is not None:
                return self._candidates[existing_id]

        assembly.check_banned(request)

        candidate = ContentCandidate(
            id=new_candidate_id(),
            body=assembly.assemble_body(request),
            product_id=request.product_id,
            channel=request.channel,
            content_type=request.content_type,
            evidence_refs=["inmemory:deterministic-assembly"],
            status="pending_review",
            idempotency_key=request.idempotency_key,
        )
        self._candidates[candidate.id] = candidate
        if request.idempotency_key is not None:
            self._idempotency[request.idempotency_key] = candidate.id
        return candidate

    async def review(
        self,
        candidate_id: str,
        decision: ReviewDecisionId,
        *,
        final_body: dict[str, Any] | None = None,
        note: str | None = None,
        reviewer_id: str | None = None,
    ) -> ContentCandidate:
        candidate = await self.get(candidate_id)
        if candidate.status != "pending_review":
            raise ContentCandidateNotReviewable(
                f"candidate is {candidate.status}, only pending_review accepts decisions"
            )

        if decision == "modified":
            if final_body is None:
                raise ContentRequestInvalid("decision=modified requires a replacement final_body")
            candidate.final_body = final_body
        elif decision == "confirmed":
            candidate.final_body = dict(candidate.body)
        # rejected：不固化 final_body。

        candidate.status = decision
        candidate.review_note = note
        candidate.reviewed_by = reviewer_id
        candidate.reviewed_at = now_utc()
        return candidate

    async def get(self, candidate_id: str) -> ContentCandidate:
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            raise ContentCandidateNotFound(candidate_id)
        return candidate
