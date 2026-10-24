"""内容底座后端抽象接口（M4/T-M4-01）。

一个 ContentBackend 负责把 ContentRequest 变成 ContentCandidate，并承接人审。
skill7 是本仓默认后端（T-M4-02 接入）；内存实现用于测试与离线演练。
接口只描述通用契约，不暴露任何 PWS/FCW 私域概念。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.core.content_base.types import (
    ContentCandidate,
    ContentRequest,
    ReviewDecisionId,
)


@runtime_checkable
class ContentBackend(Protocol):
    """内容后端协议：提交请求、人审候选、读取候选。"""

    async def submit(self, request: ContentRequest) -> ContentCandidate:
        """把请求转为 pending_review 候选；同 idempotency_key 不重复产出。"""
        ...

    async def review(
        self,
        candidate_id: str,
        decision: ReviewDecisionId,
        *,
        final_body: dict[str, Any] | None = None,
        note: str | None = None,
        reviewer_id: str | None = None,
    ) -> ContentCandidate:
        """对 pending_review 候选裁决：confirmed/modified/rejected。

        modified 必须给 final_body；非 pending_review 候选拒绝裁决。
        """
        ...

    async def get(self, candidate_id: str) -> ContentCandidate:
        """按 id 读取候选；不存在抛 ContentCandidateNotFound。"""
        ...
