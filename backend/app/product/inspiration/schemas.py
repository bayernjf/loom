"""段3 灵感库 Pydantic 契约。Actor 复用段1 口径。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.product.product_intake.schemas import Actor


class InspirationCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    layer: Literal["common", "product"]  # 限定两枚举（与 INSPIRATION_LAYERS 对齐）
    product_space_id: str | None = None
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    actor: Actor


class InspirationUpdate(BaseModel):
    content: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None
    actor: Actor


class InspirationDelete(BaseModel):
    actor: Actor


class InspirationView(BaseModel):
    entry_id: str
    tenant_id: str
    layer: str
    product_space_id: str | None = None
    content: str
    tags: list[str] = Field(default_factory=list)
    enabled: bool
    usage_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
