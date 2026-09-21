"""Q151 SLA sweep 的 PG 行级 fencing（C1.95，接 Q133 LockLease.fence）。

Q139（C1.83）只在每个作业**开始前** ``raise_if_lost()`` 协作中止；本模块把令牌
落到下游 DB 行级条件更新，挡住锁在**单个作业执行期间**（会话已开、尚未提交）
易主后旧 leader 的迟到写入（重复升级待办/重复释放冷却/重复激活词表）。

两段式（均只在 fence 非 None，即开启多副本锁时生效），形态与 Q143
``restock/fencing.py`` 同构，区别仅在认领粒度＝循环级锁名（每锁一行）而非
补货请求 id：

1. tick 开始短事务 :func:`claim_tick`：把该锁的认领行 fence 升到自己
   （插入或单调覆盖更小值），**先提交**，让易主后的新 leader 可见；若已存在
   更大 fence，说明自己是旧 leader，直接放弃本轮。
2. 每个作业与其业务数据同事务提交前 :func:`fence_current`：一条
   ``UPDATE ... WHERE lock_name=:name AND fence=:token`` 条件更新，
   rowcount=0 即已被更大 fence 的新 leader 抢占，调用方回滚该作业并中止本轮。

fence 为 None（锁关闭，V1 单副本）时不写表、不做门，行为与 Q89/Q139 一致。
"""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sla.models import SweepTickClaim

# claim_tick 结果：acquired=本次取得（新插入或把更小 fence 升到自己）；
# held=同 fence 重入（自己已认领）；lost=已存在更大 fence（旧 leader，应放弃）。
TICK_ACQUIRED = "acquired"
TICK_HELD = "held"
TICK_LOST = "lost"


async def claim_tick(
    session: AsyncSession,
    lock_name: str,
    fence: int | None,
    owner: str | None = None,
) -> str:
    """tick 开始前认领该循环锁（调用方负责在独立短事务里提交）。

    fence 为 None（锁关闭）时直接返回 held，不写表——V1 单副本路径零变化。
    """

    if fence is None:
        return TICK_HELD
    existing = await session.get(SweepTickClaim, lock_name)
    if existing is None:
        session.add(
            SweepTickClaim(lock_name=lock_name, fence=fence, claimed_by=owner)
        )
        return TICK_ACQUIRED
    if existing.fence == fence:
        return TICK_HELD
    if existing.fence < fence:
        existing.fence = fence
        existing.claimed_by = owner
        existing.claimed_at = datetime.now(UTC)
        return TICK_ACQUIRED
    return TICK_LOST


async def fence_current(
    session: AsyncSession, lock_name: str, fence: int | None
) -> bool:
    """提交前门：条件更新命中 1 行表示仍由本 fence 持有，可提交作业结果。

    与作业业务变更在**同一事务**内执行：WHERE 携带 fence，旧 leader（其 fence
    已被更大值覆盖）命中 0 行，且行锁把与新 leader 的认领升级串行化。fence 为
    None 时恒放行（V1 单副本）。
    """

    if fence is None:
        return True
    result = await session.execute(
        update(SweepTickClaim)
        .where(
            SweepTickClaim.lock_name == lock_name,
            SweepTickClaim.fence == fence,
        )
        .values(updated_at=datetime.now(UTC))
    )
    return result.rowcount == 1
