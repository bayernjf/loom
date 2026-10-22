"""内容底座持久化表（M4/T-M4-02，设计 §4.5）。

``content_candidates``：通用内容候选，不绑 PWS/intake/workflow，
状态机与 skill7 候选同构（pending_review→confirmed/modified/rejected）。
迁移 0065 建表。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid1()))


class ContentCandidateRecord(Base):
    __tablename__ = "content_candidates"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_content_candidates_idempotency_key"),
    )

    candidate_id: Mapped[str] = _uuid_pk()
    product_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[dict] = mapped_column(JSONType, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSONType, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, server_default="pending_review"
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    final_body: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    review_note: Mapped[str | None] = mapped_column(nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
