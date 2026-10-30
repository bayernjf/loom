"""客户访问令牌物理表（P0，2026-10-30）。

与 ``staff_api_keys``（内部人员）、``agent_api_keys``（机器/Agent）分域：本表每行
绑定到具体租户（``tenant_id``），由内部运营为该客户签发。同一客户可持多枚令牌
（多设备/轮换），吊销按 token_id；库内只存 SHA-256 哈希，明文仅签发响应返回一次。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid1()))


class ClientAccessToken(Base):
    __tablename__ = "client_access_tokens"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_client_access_token_hash"),
    )

    token_id: Mapped[str] = _uuid_pk()
    # 令牌绑定的租户；验签时必须与请求 tenant_id 一致，否则按无效凭证处理。
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 客户/客户端稳定标识（作 actor.id，如客户名或设备备注）；同租户可有多枚，故非唯一。
    client_name: Mapped[str] = mapped_column(String(128), nullable=False)
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
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
