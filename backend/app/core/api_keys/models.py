"""入站 Agent API Key 物理表（Q88，一 Agent 一 Key、可吊销）。

与 model_registry.AIModelKey 刻意分域：outbound 密钥须还原明文发给供应商，
故存 Fernet 密文；入站只需比对，故本表只存 SHA-256 哈希，库泄露不暴露可用 Key。
Key 为平台级凭证不绑租户（Q88-3，租户绑定口径原文未给【待补】）。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True)


class AgentApiKey(Base):
    __tablename__ = "agent_api_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_agent_api_key_hash"),
    )

    key_id: Mapped[str] = _uuid_pk()
    # Agent 标识/运营备注（Q60b 一 Agent 一 Key）。
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 明文 Key 的 SHA-256 hex；明文仅签发响应返回一次。
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 明文前缀展示码，供管理页辨识（不构成凭证）。
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
