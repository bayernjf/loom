"""内容底座（content-base，M4）：通用「内容请求 → 候选 → 人审」契约。

设计依据见 Tier0-设计文档 §4.5。本包只含通用契约与后端注册点，
不依赖 PWS/FCW 私域白名单；skill7 后端在 T-M4-02 经 registry 接入。

公共出口：
- 类型：ContentRequest / ContentCandidate / ContentConstraints 及类型别名
- 接口：ContentBackend
- 参考实现：InMemoryContentBackend
- 注册：register / get_backend / get_default / reset
- 错误：ContentBaseError 及子类
"""

from app.core.content_base.base import ContentBackend
from app.core.content_base.errors import (
    ContentBackendUnavailable,
    ContentBaseError,
    ContentCandidateNotFound,
    ContentCandidateNotReviewable,
    ContentRequestInvalid,
)
from app.core.content_base.memory import InMemoryContentBackend
from app.core.content_base.registry import (
    BackendNotRegistered,
    get_backend,
    get_default,
    register,
    reset,
)
from app.core.content_base.types import (
    CandidateStatus,
    ContentCandidate,
    ContentConstraints,
    ContentRequest,
    ContentTypeId,
    ReviewDecisionId,
    new_candidate_id,
    now_utc,
)

__all__ = [
    "BackendNotRegistered",
    "CandidateStatus",
    "ContentBackend",
    "ContentBackendUnavailable",
    "ContentBaseError",
    "ContentCandidate",
    "ContentCandidateNotFound",
    "ContentCandidateNotReviewable",
    "ContentConstraints",
    "ContentRequest",
    "ContentRequestInvalid",
    "ContentTypeId",
    "InMemoryContentBackend",
    "ReviewDecisionId",
    "get_backend",
    "get_default",
    "new_candidate_id",
    "now_utc",
    "register",
    "reset",
]
