"""段12 内容成品（content_products）物理模型（08 P4，V2）。

字段集原文未给出（docs/04 §3 待补，属开发第 0 步），本表为【实现补登】：
从 Q56–Q59 与段12「只读消费 FCW、生成成品、客户审阅」需求推断的最小字段。
final_id 为只读软关联（PT-ART-GEN-V1.5：只读消费、不重决策上游、不写 final_id）。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType

# Q59：载体枚举；P4 第一片只做 article，video 后置（video-studio 四模块）。
KIND_ARTICLE = "article"
KIND_VIDEO = "video"
KINDS = (KIND_ARTICLE, KIND_VIDEO)

# 状态机（见 statemachine.py）：草稿→生成中→待审阅→ready_for_publish / 驳回 / 改稿。
CONTENT_DRAFT = "draft"
CONTENT_GENERATING = "generating"
CONTENT_REVIEW = "review"
CONTENT_READY = "ready_for_publish"
CONTENT_REJECTED = "rejected"
CONTENT_REVISING = "revising"

# Q56：重生成上限 3 次，超限转人工或作废骨架回池。
MAX_REGENERATE = 3

DEFAULT_LANGUAGE = "zh-CN"  # Q58 多语言后置，P4 第一片单语言。


def _uuid_pk() -> str:
    return str(uuid.uuid1())


class ContentProduct(Base):
    """内容成品：一条 final_id 的一篇生成内容（每语言版独立成品，Q58）。"""

    __tablename__ = "content_products"

    content_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_pk)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 只读软关联 FCW（final_content_whitelists.final_id）；不设硬 FK，同 FCW 内部 id 引用口径。
    final_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    goal: Mapped[str] = mapped_column(String(32), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    slot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default=KIND_ARTICLE)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default=DEFAULT_LANGUAGE)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_hits: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CONTENT_DRAFT, index=True
    )
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    regenerate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
