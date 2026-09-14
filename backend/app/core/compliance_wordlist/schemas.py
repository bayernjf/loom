"""Q48 合规词库 Pydantic 契约。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.actor import Actor


class WordlistItem(BaseModel):
    word: str = Field(min_length=1)
    level: Literal["critical", "high"]
    action: Literal["ban", "downgrade"]
    downgrade_target: str | None = None
    country: str | None = None
    industry: str | None = None
    # Q50 层级；缺省由服务归一化（带国家→country，其余→base）。
    layer: Literal["country", "platform", "base"] | None = None


class WordlistUpsert(BaseModel):
    item: WordlistItem
    actor: Actor
