import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType
from app.core.models import AuditLog  # re-exported for M1 import paths

__all__ = [
    "AuditLog",
    "G2Field",
    "ProductIntakeApplication",
    "ProductSpace",
]


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class ProductIntakeApplication(Base):
    """段1 录入申请单（docs/04 §2.1, docs/10 §2.1）。"""

    __tablename__ = "product_intake_applications"

    intake_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 18 个 G2 cat='common' 字段的提交值，按 fid 键控；提交后不可变（Q74）。
    profile: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    # 冷启动支线关联的 B2 新类目候选单（Q5）。
    category_pending_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
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


class ProductSpace(Base):
    """段1 ProductSpace（一品一空间，docs/04 §2.2, docs/10 §2.1）。

    申请单走到 建模中 时创建；profile_snapshot 是下游唯一消费的资料副本（Q74）。
    """

    __tablename__ = "product_spaces"

    product_space_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    intake_id: Mapped[str] = mapped_column(
        ForeignKey("product_intake_applications.intake_id"),
        nullable=False,
        unique=True,
        index=True,
    )
    category_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    industry_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sensitive_industry: Mapped[bool] = mapped_column(default=False, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), default="modeling", nullable=False)
    active_pws_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    business_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_snapshot: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class G2Field(Base):
    """G2 通用字段池的最小切片（M1 只需 cat/status/fid 支撑完整度闸门）。"""

    __tablename__ = "g2_fields"

    fid: Mapped[str] = mapped_column(String(64), primary_key=True)
    cat: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
