"""内部运营个人访问令牌物理表（Q178，甲案 PAT）。

与 ``agent_api_keys``（Q88，机器/Agent 平台级凭证）分域：本表每行是一枚绑定到
具体内部人员的令牌，携带该人员的稳定标识（staff_id，作 actor.id）、显示名与签发时
绑定的角色快照。同一 staff_id 可持多枚令牌（轮换），吊销按 key_id；人员改角色＝
签发新令牌并吊销旧令牌（YAGNI：不拆 staff_accounts/tokens 两表）。

库内只存 SHA-256 哈希（库泄露不暴露可用令牌）；明文仅签发响应返回一次。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid1()))


class StaffApiKey(Base):
    __tablename__ = "staff_api_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_staff_api_key_hash"),
    )

    key_id: Mapped[str] = _uuid_pk()
    # 人员稳定标识（工号/登录名，作 actor.id）；同一人可有多枚令牌，故非唯一。
    staff_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    staff_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 签发时绑定的内部角色码快照（list[str]，JSONB on PG / JSON on sqlite）。
    roles: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    # 明文令牌的 SHA-256 hex；明文仅签发响应返回一次。
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 明文前缀展示码，供管理页辨识（不构成凭证）。
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
