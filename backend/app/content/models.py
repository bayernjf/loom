"""段12 内容成品（content_products）物理模型（08 P4，V2）。

字段集原文未给出（docs/04 §3 待补，属开发第 0 步），本表为【实现补登】：
从 Q56–Q59 与段12「只读消费 FCW、生成成品、客户审阅」需求推断的最小字段。
final_id 为只读软关联（PT-ART-GEN-V1.5：只读消费、不重决策上游、不写 final_id）。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, func
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
    __table_args__ = (
        # Q119/Q58：一条 final_id 每语言每载体仅一个独立成品（独立复检/独立客户审）。
        UniqueConstraint(
            "final_id", "language", "kind", name="uq_content_final_language_kind"
        ),
    )

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
    # Q120/Q57：AI 质量分（模型网关第 8 场景 ARTICLE-QC）。定位仅为辅助参考，不阻断
    # 发证（Q57）；score 0..1，issues 为问题明细；QC 不可用时 score 留空、issues 记 qc_error。
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_issues: Mapped[list | None] = mapped_column(JSONType, nullable=True)
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

# Q119/Q58：语言清单状态。
LANGUAGE_ACTIVE = "active"
LANGUAGE_ARCHIVED = "archived"


class ContentLanguage(Base):
    """段12 内容语言清单（Q58「支持语言清单配置化」，Q119 落地）。

    code 为 BCP-47 语言标签（如 zh-CN/en-US）；markets 为适用市场国家码
    （对齐 FCW.country，String(8)），空列表表示适用全部市场（含 country 为空）。
    可生成语言 = 清单中 markets 覆盖发布位市场（FCW.country）的 active 语言，
    再与 ProductSpace.target_languages 取交集（Q58：发布位市场 ∩ 产品目标语言）。
    """

    __tablename__ = "content_languages"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    markets: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=LANGUAGE_ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
