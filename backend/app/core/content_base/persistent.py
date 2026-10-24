"""持久内容后端（M4/T-M4-02）：ContentBackend 的 DB 实现，委托 service。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content_base import service
from app.core.content_base.base import ContentBackend
from app.core.content_base.types import (
    ContentCandidate,
    ContentRequest,
    ReviewDecisionId,
)


class PersistentContentBackend(ContentBackend):
    """每次请求绑定一个 session 的持久后端。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def submit(self, request: ContentRequest) -> ContentCandidate:
        record = await service.submit_candidate(self._session, request)
        return service.to_candidate(record)

    async def review(
        self,
        candidate_id: str,
        decision: ReviewDecisionId,
        *,
        final_body: dict[str, Any] | None = None,
        note: str | None = None,
        reviewer_id: str | None = None,
    ) -> ContentCandidate:
        record = await service.review_candidate(
            self._session,
            candidate_id,
            decision,
            final_body=final_body,
            note=note,
            reviewer_id=reviewer_id,
        )
        return service.to_candidate(record)

    async def get(self, candidate_id: str) -> ContentCandidate:
        record = await service.get_candidate(self._session, candidate_id)
        return service.to_candidate(record)
