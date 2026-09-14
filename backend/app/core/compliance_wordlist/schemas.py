"""Q48 合规词库 Pydantic 契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
    # Q48 生效期（可空=立即生效且长期有效）；未来生效词条由 M10 调度到点补扫（Q51）。
    effective_from: datetime | None = None
    effective_until: datetime | None = None

    @model_validator(mode="after")
    def _check_window(self) -> "WordlistItem":
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_until < self.effective_from
        ):
            raise ValueError("effective_until must not be earlier than effective_from")
        return self


class WordlistUpsert(BaseModel):
    item: WordlistItem
    actor: Actor
