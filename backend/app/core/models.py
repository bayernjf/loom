"""横切 ORM 模型（writeAudit 等跨模块共享表）。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class AuditLog(Base):
    """writeAudit: append-only audit trail (docs/15 §3, D3.11).

    Rows are only inserted; never updated or deleted by application code.
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_roles: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
