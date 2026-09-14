"""Q48 统一合规词库 ORM 模型（段4 定原子风险 / 段5 相撞合规 / 段10 清洗，三关卡同源）。

字段：词/等级(critical|high)/处置(ban 禁用|downgrade 降级)/降级映射目标/
适用国家/适用行业/生效期；全部 CRUD + 审计（Q48）。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class ComplianceWordlistEntry(Base):
    __tablename__ = "compliance_wordlist"

    entry_id: Mapped[str] = _uuid_pk()
    word: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(8), nullable=False)  # critical/high
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # ban/downgrade
    downgrade_target: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # None = 适用于全部国家/行业（Q48：适用国家/适用行业）。
    country: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Q50 规则层级：country 国家法规 > platform 平台规则 > base 底座默认（不可配置）。
    layer: Mapped[str] = mapped_column(
        String(8), nullable=False, default="base", server_default="base"
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", index=True
    )  # active/archived
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
