"""段10 ORM 模型：CP-LAW 敏感领域清单（Q48 独立小表）、法审记录（Q49）、CCR 清洗报告。

历史清洗结果只增不 mutate（PT-COMPLIANCE-V2.0：历史 SkillRunLog 不可 mutate，
即便回滚）——重跑生成新报告行，段11 Guard 消费每市场最新一行。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CpLawSensitiveDomain(Base):
    """CP-LAW 敏感领域清单（领域非词，04 §2.20）：医疗健康/儿童/减肥/美白/医疗器械/金融。"""

    __tablename__ = "cp_law_sensitive_domains"

    domain_id: Mapped[str] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class LawReview(Base):
    """法审记录（Q49）：敏感领域自动触发，结论为线下律师审查的系统录入。

    一个冻结版本一条（幂等）；通过 → 段11 Guard⑥ 放行；不通过 → 一票否决。
    """

    __tablename__ = "law_reviews"
    __table_args__ = (
        UniqueConstraint("pws_id", name="uq_law_review_pws"),
    )

    law_review_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    pws_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()


class CcrReport(Base):
    """CCR 清洗报告（WF-08 COMPLIANCE/CLAIM-DOWNGRADE 的落库结果，分市场独立判）。

    报告行 append-only：重跑产新行；hits 为 Q50 裁决后的每词一条结果。
    block_required=true 时令段11 Guard② 失败、WF-09 必须中止（PT-COMPLIANCE-V2.0）。
    """

    __tablename__ = "ccr_reports"

    ccr_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid1())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    pws_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # None = 不按市场细分（底座通用判定）；非空 = 该国家市场的独立判定。
    country: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    block_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hits: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    wordlist_context: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    run_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()
