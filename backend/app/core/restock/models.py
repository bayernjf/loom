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


class RestockClaim(Base):
    """Q143 restock 花钱处理的 PG 行级 fencing 认领栅栏（C1.87）。

    每个 requested 信号行最多对应一条认领行，记录当前获准处理它的 leader
    fencing token（Q133 ``LockLease.fence``，按锁名单调递增）。leader 在调模型
    花钱前以短事务认领（插入/把 fence 升到自己），成功结果与业务数据在同一事务
    提交前用 ``WHERE request_id=:id AND fence=:token`` 条件更新做门：锁在一轮
    花钱中途易主、新 leader 以更大 fence 认领后，旧 leader 的迟到结果条件更新
    命中 0 行，整轮回滚，重复候选不落库。

    关闭多副本锁（V1 单副本默认）时 fence 为 None，不写本表、不做门，行为与
    Q87/Q139 完全一致。外部模型调用本身不可撤销，fence 只保护下游 DB 写入一致
    性（挡重复候选/子 run），不回收已发生的模型花费。
    """

    __tablename__ = "restock_claims"

    # = requested/restock_auto 信号行的 run_id（uuid 字符串）。
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # 当前获准处理该信号的最大 fencing token（单调，只升不降）。
    fence: Mapped[int] = mapped_column(Integer, nullable=False)
    # 认领方 owner_token（溯源，可空）。
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
