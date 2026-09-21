"""Q151 SLA sweep tick 的 PG 行级 fencing 认领栅栏表（C1.95）。

与 Q143 ``restock_claims``（per-request 一行）的粒度不同：SLA sweep 是周期性
全表维护作业、没有外部请求游标，故按**循环级锁名**每把锁一行（upsert 语义），
记录本 tick 当前获准写下游的最大 Q133 fencing token。leader 在一轮 tick 开始
以短事务认领（插入/把 fence 升到自己），每个作业与其业务变更在同一事务提交前
用 ``WHERE lock_name=:name AND fence=:token`` 条件更新做门：锁在该作业执行
期间易主、新 leader 以更大 fence 认领后，旧 leader 的迟到提交命中 0 行，整个
作业回滚、本轮剩余作业不再执行。

关闭多副本锁（V1 单副本默认）时 fence 为 None，不写本表、不做门，行为与
Q89/Q139 完全一致。SLA 作业不花外部 token，fence 只保证下游 DB 写入一致性，
不涉及不可撤销花费。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SweepTickClaim(Base):
    __tablename__ = "sweep_tick_claims"

    # 循环级锁名（如 app.core.locking.SWEEP_LOCK = loom:lock:sla-sweep）。
    lock_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    fence: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
