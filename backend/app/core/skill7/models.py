"""skill7 横切表（M10 切片 e，迁移 0012；Q79-4 intake 锚点见迁移 0013；字段级补登见 docs/10 §2.8）。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid1()))


class SkillRun(Base):
    """SkillRunLog：每次输入/输出/成本/置信度/失败留痕，append-only。

    PT-COMPLIANCE-V2.0：历史 SkillRunLog 不可 mutate（即便回滚）。
    status=requested 用于系统触发但尚无产出的运行（Q71 补货，Q76-4）。
    """

    __tablename__ = "skill_runs"

    run_id: Mapped[str] = _uuid_pk()
    skill_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    wf_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    product_space_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    # Q79-4：段2（WF-01）先于 ProductSpace，intake 锚点与 PS 锚点二选一。
    intake_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    input_payload: Mapped[dict | None] = mapped_column("input", JSONType, nullable=True)
    output_payload: Mapped[dict | None] = mapped_column("output", JSONType, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Q82：真 LLM 调用的模型归属与 per-1M 折算成本（币种原文未给【待补】）。
    model_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    input_cost: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    output_cost: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class SkillCandidate(Base):
    """skill7 通用候选（15 §3 Candidate → Review/Confirm → Applied 管道，Q76-3）。

    正式对象不直接写：confirmed/modified 后由 target_type 适配器落既有业务表，
    applied_refs 回写结果；rejected → archived（05 §2.3）。
    """

    __tablename__ = "skill_candidates"
    __table_args__ = (
        UniqueConstraint("run_id", "candidate_index", name="uq_skill_candidate_run_index"),
    )

    candidate_id: Mapped[str] = _uuid_pk()
    run_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    candidate_index: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    wf_id: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    product_space_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )  # Q79-4：c1_recognition 走 intake 锚点，故改 nullable
    intake_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    applied_refs: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    human_modified: Mapped[bool] = mapped_column(default=False, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
