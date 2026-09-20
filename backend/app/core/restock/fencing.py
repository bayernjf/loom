"""Q143 restock 花钱处理的 PG 行级 fencing（C1.87，接 Q133 LockLease.fence）。

Q133（C1.77）只发单调 fencing token、Q139（C1.83）在每条信号处理前协作式
``raise_if_lost()``；本模块把令牌落到下游 DB 行级条件更新，挡住锁在**一次模型
调用期间**易主后旧 leader 的迟到成功结果（重复候选/子 run）落库。

两段式（均只在 fence 非 None，即开启多副本锁时生效）：

1. 花钱前短事务 :func:`claim_request`：把该 request 的认领行 fence 升到自己
   （插入或单调覆盖更小值），**先提交**，让易主后的新 leader 可见；若已存在更大
   fence，说明自己是旧 leader，直接放弃，不再调模型。
2. 成功结果与业务数据同事务提交前 :func:`fence_current`：一条
   ``UPDATE ... WHERE request_id=:id AND fence=:token`` 条件更新，rowcount=0 即
   已被更大 fence 的新 leader 抢占，调用方回滚整轮、不提交候选。

边界（如实记录）：外部模型调用已花的钱不可撤销，fence 只保证下游 DB 不出现旧
leader 的重复结果；失败/瞬态路径（deferred/failed、退避游标）不产候选、幂等，
不接此门。V1 单副本（锁关闭、fence=None）不写表、不做门，行为与 Q87/Q139 一致。
"""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.restock.models import RestockClaim

# claim_request 结果：acquired=本次取得（新插入或把更小 fence 升到自己）；
# held=同 fence 重入（自己已认领）；lost=已存在更大 fence（旧 leader，应放弃）。
CLAIM_ACQUIRED = "acquired"
CLAIM_HELD = "held"
CLAIM_LOST = "lost"


async def claim_request(
    session: AsyncSession,
    request_id: str,
    fence: int | None,
    owner: str | None = None,
) -> str:
    """花钱前认领该 request（调用方负责在独立短事务里提交）。

    fence 为 None（锁关闭）时直接返回 held，不写表——V1 单副本路径零变化。
    """

    if fence is None:
        return CLAIM_HELD
    existing = await session.get(RestockClaim, request_id)
    if existing is None:
        session.add(
            RestockClaim(
                request_id=request_id, fence=fence, claimed_by=owner
            )
        )
        return CLAIM_ACQUIRED
    if existing.fence == fence:
        return CLAIM_HELD
    if existing.fence < fence:
        existing.fence = fence
        existing.claimed_by = owner
        existing.claimed_at = datetime.now(UTC)
        return CLAIM_ACQUIRED
    return CLAIM_LOST


async def fence_current(
    session: AsyncSession, request_id: str, fence: int | None
) -> bool:
    """提交前门：条件更新命中 1 行表示仍由本 fence 持有，可提交结果。

    与成功结果在**同一业务事务**内执行：WHERE 携带 fence，旧 leader（其 fence 已
    被更大值覆盖）命中 0 行，且行锁把与新 leader 认领升级的判定串行化。fence 为
    None 时恒放行（V1 单副本）。
    """

    if fence is None:
        return True
    result = await session.execute(
        update(RestockClaim)
        .where(
            RestockClaim.request_id == request_id,
            RestockClaim.fence == fence,
        )
        .values(updated_at=datetime.now(UTC))
    )
    return result.rowcount == 1
