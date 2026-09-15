"""Q90 restock 瞬态失败退避游标表。

执行态而非业务事实日志：requested 信号行（skill_runs）受 Q87 append-only
纪律永不 mutate，重试次数/下次可重试时间落本表 upsert；信号成功或转终态后
删除游标行（审计轨迹 restock_deferred/restock_failed 不受影响）。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RestockRetryState(Base):
    __tablename__ = "restock_retry_state"

    # = requested/restock_auto 信号行的 run_id（uuid 字符串）。
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
