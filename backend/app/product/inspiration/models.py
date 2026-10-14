"""段3 灵感库本体（product-inspiration，MVP 模块，产品基准段3 法定拆维度来源）。

两层：
- common（租户内通用，product_space_id 为 NULL，供该租户所有产品取用）；
- product（绑定单个 product_space_id，仅该产品专属）。

运营可增删改条目；DIM-SOURCE 在生成维度候选时按 tenant/layer 拉取 enabled 条目作为
依据内容（docs/01 段3 line 72、docs/24 §5.2、docs/25 Q8）。

禁止臆造：种子零行，内容由运营/客户真实填充（不落任何假数据）。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType

LAYER_COMMON = "common"
LAYER_PRODUCT = "product"
INSPIRATION_LAYERS = frozenset({LAYER_COMMON, LAYER_PRODUCT})


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InspirationEntry(Base):
    """一条灵感：拆维度时可引用的法定来源内容（用户输入外的知识层来源之一）。"""

    __tablename__ = "inspiration_entries"

    entry_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    layer: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    product_space_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
