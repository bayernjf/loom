"""段 3 案例证据库（case_evidence，DIM-SOURCE 第 7 路来源）。

「同类好内容 / 案例」独立来源路：与 ``inspiration_entries``（灵感库，特有表达 /
用户评论 / 问答）语义区分——本表只收可追溯的同类好内容案例，作为 DIM-MERGE
拆维度时的法定依据来源（docs/design-q324-candidate-review.md §DIM-SOURCE 甲案）。

禁止臆造：种子零行，内容由运营/客户真实填充（不落任何假数据）；连接器
fail-closed 为空时不编造来源。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CaseEvidence(Base):
    """一条案例证据：同类好内容/案例，拆维度时可引用的第 7 路来源内容。"""

    __tablename__ = "case_evidence"

    case_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
