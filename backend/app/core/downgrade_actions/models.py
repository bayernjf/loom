"""Q38 降级动作字典 ORM（载体随 Q306 落，docs/02:141／docs/10 §dict_management）。

动作项＝「AI 降级建议只能从这里选」的可选集；`name`/`why` 原文未给出具体文案
⇒ 种子留 NULL 待运营回填，界面先显示 code（禁臆造业务事实）。
CP-DOWN 的词级映射目标不在本表（已由 Q48 `compliance_wordlist.downgrade_target` 承载）。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

ACTIVE = "active"
ARCHIVED = "archived"


class DowngradeAction(Base):
    __tablename__ = "downgrade_actions"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    why: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ACTIVE, server_default=ACTIVE, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
