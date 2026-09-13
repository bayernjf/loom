"""段4 ORM 模型：拓展批次、原子候选、AtomConflict、正式原子实例。

依据 docs/04 §2.8/2.9、atom8（line 1454）、PT-ATOM-EXP-V1.3（line 2013）、
AtomConflict（line 840）、Q14-Q20、line 11189（产品事实原子引用数=1）。
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


class AtomBatch(Base):
    """一次原子拓展批次（Q14：敏感默认 20/非敏感 50，运营可手动改）。"""

    __tablename__ = "atom_batches"

    batch_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(
        ForeignKey("product_spaces.product_space_id"), nullable=False, index=True
    )
    pool_id: Mapped[str] = mapped_column(
        ForeignKey("field_pools.pool_id"), nullable=False
    )
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # ai=Skill 自动拓展（达标即停，Q15）；manual=运营手动追加批次。
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="ai")
    sensitive_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class AtomCandidate(Base):
    """WF-03 原子候选：PT-ATOM-EXP 仅产 candidate，Gate 通过才派生正式实例。"""

    __tablename__ = "atom_candidates"
    __table_args__ = (
        UniqueConstraint("batch_id", "normalized", name="uq_atom_candidate_batch_dedup"),
    )

    candidate_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("atom_batches.batch_id"), nullable=False, index=True
    )
    product_space_id: Mapped[str] = mapped_column(
        ForeignKey("product_spaces.product_space_id"), nullable=False, index=True
    )
    pool_id: Mapped[str] = mapped_column(
        ForeignKey("field_pools.pool_id"), nullable=False, index=True
    )
    dimension_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # 候选挂载的维度 fid（approveAtomGuard②：属选中 FieldPool）。
    fid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized: Mapped[str] = mapped_column(String(512), nullable=False)
    # None=通用人类表达原子；取值见 atom_rules.PRODUCT_FACT_TYPES（line 11189）。
    fact_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    risk_level: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    risk_source: Mapped[str] = mapped_column(String(16), nullable=False)  # wordlist/ai/manual
    matched_words: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)

    affinity: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_affinity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Q19 同义词簇：同 cluster_id，人工终裁后非 keeper 置 merged。
    cluster_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # 被合并文本不删：Gate 通过 keeper 时落到正式实例 aliases，供生成同义替换。
    aliases: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    alias_of: Mapped[str | None] = mapped_column(String(36), nullable=True)

    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # approveAtomGuard⑦：一个候选最多派生一个正式实例。
    approved_atom_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = _created_at()
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AtomConflict(Base):
    """AtomConflict（docs/04 §2.9，line 840，字段完整）。"""

    __tablename__ = "atom_conflicts"

    conflict_id: Mapped[str] = _uuid_pk()
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("atom_candidates.candidate_id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # blocked/pending_gate
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ProductAtomInstance(Base):
    """ProductAtomInstance（docs/04 §2.8）：Gate 通过后的正式原子，走 atom8 生命周期。"""

    __tablename__ = "product_atom_instances"
    __table_args__ = (
        UniqueConstraint(
            "fact_type",
            "normalized",
            name="uq_product_fact_atom_value",
        ),
    )

    atom_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(
        ForeignKey("product_spaces.product_space_id"), nullable=False, index=True
    )
    pool_id: Mapped[str] = mapped_column(
        ForeignKey("field_pools.pool_id"), nullable=False, index=True
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("atom_candidates.candidate_id"), nullable=False
    )
    dimension_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized: Mapped[str] = mapped_column(String(512), nullable=False)
    fact_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    aliases: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)

    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    risk_source: Mapped[str] = mapped_column(String(16), nullable=False)
    affinity: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    # approved/frozen/deprecated/rejected/compliance_suspended/archived
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reference_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
