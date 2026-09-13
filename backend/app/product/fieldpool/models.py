"""段3 ORM 模型：来源路由表（Q8）、FieldPool、池内维度。

依据 docs/04 §2.6/2.7、PT-FP-PLAN-V2.0、Q8-Q13/Q15、docs/10。
新字段不在此建表：统一进 M2 的 g2_field_candidates，Q13 Gate 转正。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FPSourceRoute(Base):
    """Q8 维度来源路由表：运营可增删改；每路产出必须带依据标注。"""

    __tablename__ = "fp_source_routes"

    route: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created_at()


class FieldPool(Base):
    """FieldPool（docs/04 §2.7）：一品一池；第一期方案全部 pending_gate 走人工 Gate。

    rejected 后允许同 PS 重新提交（覆盖维度行、留审计）；approved 后不可改。
    """

    __tablename__ = "field_pools"
    __table_args__ = (
        UniqueConstraint("product_space_id", name="uq_field_pool_product_space"),
    )

    pool_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(
        ForeignKey("product_spaces.product_space_id"), nullable=False, index=True
    )
    gate: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending_gate", index=True
    )  # pending_gate/approved/rejected
    compliant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    violations: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    target_atom_min: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    target_atom_max: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    submitted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FPDimension(Base):
    """池内维度行：角色/来源/依据/置信度 + Q10 疑似重复标记。

    fid 非空=复用 G2 既有字段；candidate_id 非空=新字段候选（Q13 转正后回填 fid）。
    status：selected（Top8 内）/ backup（Q12 备选档，人工可捞回，不删）。
    """

    __tablename__ = "fp_dimensions"

    dimension_id: Mapped[str] = _uuid_pk()
    pool_id: Mapped[str] = mapped_column(
        ForeignKey("field_pools.pool_id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_route: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    fid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    needs_detail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    related_fid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="selected", index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
