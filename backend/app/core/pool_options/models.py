"""Q43 17 池选项字典 ORM（载体随 Q308 落，docs/02:155／docs/10 §dict_management）。

一行一池：`pool` 是池名（＝`pa_rules.WEIGHT_KEYS_17` 那 17 个键），`options` 是该池的
可选值列表。段9 选料只能从这张字典里选（Q43），**运行期强校验随段9/12 接线点工**，
本表只提供可选集与管理面。
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

ACTIVE = "active"
ARCHIVED = "archived"

json_type = JSON().with_variant(postgresql.JSONB(), "postgresql")


class PoolOption(Base):
    __tablename__ = "pool_options"

    pool: Mapped[str] = mapped_column(String(32), primary_key=True)
    options: Mapped[list] = mapped_column(json_type, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ACTIVE, server_default=ACTIVE, index=True
    )
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
