"""内容底座通用契约（设计 §4.5，M4/T-M4-01）。

剥离 PWS/FCW 私域概念（product_space / workflow / pwc target_type），
只保留「内容请求 → 候选 → 人审」的通用语言。

零框架依赖：本模块不导入 sqlalchemy / pydantic / skill7，可被 commerce 等
任意面复用；合规词库一律由调用方经 ContentConstraints 注入，底座不内置
任何私域白名单（T-M4-01 验收口径）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

# 设计 §4.5 四类电商内容。
ContentTypeId = Literal["detail", "post", "short_video_script", "qa"]

# 复用 skill7 候选裁决三态（设计 §4.5 review）。
ReviewDecisionId = Literal["confirmed", "modified", "rejected"]

# 候选生命周期：产出即 pending_review，人审后落 confirmed/modified/rejected。
CandidateStatus = Literal["pending_review", "confirmed", "modified", "rejected"]


def new_candidate_id() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ContentConstraints:
    """内容产出约束，由调用方注入；底座不内置私域白名单。

    wordlist：合规/可用词提示；banned：禁用词，命中即拦截；
    brand：品牌词，供产出保持口径一致。
    """

    wordlist: list[str] = field(default_factory=list)
    banned: list[str] = field(default_factory=list)
    brand: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContentRequest:
    """一次内容产出请求（设计 §4.5 ContentRequest）。"""

    product_id: str
    channel: str
    content_type: ContentTypeId
    inputs: dict[str, Any] = field(default_factory=dict)
    constraints: ContentConstraints = field(default_factory=ContentConstraints)
    # 幂等键：同键重复请求不重复产出（设计 §4.7 幂等口径）。
    idempotency_key: str | None = None
    # 产出语言（T-M9-02，如 zh-CN/en-US）：None = 调用方默认语言，向后兼容。
    locale: str | None = None


@dataclass
class ContentCandidate:
    """内容候选（设计 §4.5 ContentCandidate），产出即 pending_review。"""

    id: str
    body: dict[str, Any]
    product_id: str
    channel: str
    content_type: ContentTypeId
    evidence_refs: list[str] = field(default_factory=list)
    status: CandidateStatus = "pending_review"
    idempotency_key: str | None = None
    # 人审后的最终 body：confirmed 时等于 body，modified 时为替换体。
    final_body: dict[str, Any] | None = None
    review_note: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = field(default_factory=now_utc)
