"""内容底座错误类型（M4/T-M4-01）。

错误口径与组合级 §4.7 对齐：契约/状态类错误 fail-closed，不允许静默降级。
"""

from __future__ import annotations


class ContentBaseError(Exception):
    """内容底座错误基类。"""


class ContentRequestInvalid(ContentBaseError):
    """请求契约不合法（未知 content_type、缺必填字段、命中 banned 等）。"""


class ContentCandidateNotFound(ContentBaseError):
    """候选不存在。"""

    def __init__(self, candidate_id: str) -> None:
        super().__init__(f"content candidate not found: {candidate_id}")
        self.candidate_id = candidate_id


class ContentCandidateNotReviewable(ContentBaseError):
    """候选不在 pending_review，不能再裁决。"""


class ContentBackendUnavailable(ContentBaseError):
    """底层后端（模型网关 / skill7）不可用；调用方应 fail-closed，不本地兜底产出。"""
