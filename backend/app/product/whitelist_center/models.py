"""段6 ORM 模型：PWS 不可变快照、快照明细行、冻结日志（Q28-Q33）。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
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


class PwsSnapshot(Base):
    """产品白名单冻结快照（04 §2.11，Q31）：不可变、全保留、同刻仅 1 个 active。

    status: frozen（可消费）/ superseded（旧版只读）/ revoked（急停断消费，Q32）。
    下游段 7-11 只能消费 is_active=True 且 status=frozen 的版本（段11 Guard⑦）。
    """

    __tablename__ = "pws_snapshots"
    __table_args__ = (
        UniqueConstraint("product_space_id", "version", name="uq_pws_ps_version"),
    )

    pws_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(
        ForeignKey("product_spaces.product_space_id"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)

    pool_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    snapshot: Mapped[dict] = mapped_column(JSONType, nullable=False)
    readiness: Mapped[dict] = mapped_column(JSONType, nullable=False)
    refreeze_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    revoked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class PwsSnapshotItem(Base):
    """快照明细行（docs/10 §2.3 pws_items【建议】落库）：原子/PWC 引用 + 内容快照。

    快照后源实体变化不影响本行——不可变快照的物化保证（Q31）。
    """

    __tablename__ = "pws_snapshot_items"
    __table_args__ = (
        UniqueConstraint("pws_id", "kind", "ref_id", name="uq_pws_item_ref"),
    )

    item_id: Mapped[str] = _uuid_pk()
    pws_id: Mapped[str] = mapped_column(
        ForeignKey("pws_snapshots.pws_id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # atom/pwc
    ref_id: Mapped[str] = mapped_column(String(36), nullable=False)
    dimension_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)


class PwsFreezeLog(Base):
    """冻结/重冻/换版/急停日志（docs/10 §2.3 pws_freeze_logs【建议】）。

    每次红线动作记触发原因 + 操作人 + Q 依据；状态只增不 mutate。
    """

    __tablename__ = "pws_freeze_logs"

    log_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    pws_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(24), nullable=False)
    # freeze / refreeze / supersede / revoke
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created_at()
