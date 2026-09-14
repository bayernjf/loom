"""M10 配置中心表：统一配置项 + 版本历史（02 §C2 / 07 §2.4 §7.4 / 14 §2.4）。

- config_items：key 唯一，typed JSON 值，校验规则与出处 Q 编号随行走元数据；
  新键只随代码+迁移种子进入（运营改值不造键，保证类型/校验/出处可溯）。
- config_item_versions：每次发布写新版本行，支持一键回滚到历史版本
  （14 §2.4：发布=新版本 + 原子切换 + writeAudit，自带版本回滚）。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType


def _uuid_pk() -> str:
    return str(uuid.uuid1())


def _now() -> datetime:
    return datetime.now(UTC)


class ConfigItem(Base):
    __tablename__ = "config_items"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSONType, nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # 通用校验（07 §7.4）：{"min": x, "max": y, "choices": [...]}，可空。
    validation: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    source_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now(), nullable=False
    )


class ConfigItemVersion(Base):
    __tablename__ = "config_item_versions"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_config_version_key_version"),
    )

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_pk)
    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[dict] = mapped_column(JSONType, nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    changed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
