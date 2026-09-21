"""后台 sweep 调度器：定时跑统一 runner（Q49）。

Q89：多副本下用 Redis 分布式锁保证同一时刻只有一个副本跑 sweep；锁关闭时
（默认，单副本）行为与直接循环一致。Q139：锁一轮 tick 中途易主（看门狗续约
返回 0 或续约期 Redis 故障）时协作中止，本轮剩余作业不再执行，下轮重新抢锁。
Q151：tick 开始先以 PG 行级 fence 认领（短事务提交），每个作业提交前再过
fence_current 条件更新门，挡住锁在单作业执行期间易主后的迟到写入。
"""

import asyncio
import contextlib
import logging

from app.core.locking import (
    SWEEP_LOCK,
    LockBackendError,
    LockLost,
    LockUnavailable,
    leader_lease,
)
from app.core.sla.fencing import (
    TICK_LOST,
    claim_tick,
    fence_current,
)
from app.core.sla.runner import run_jobs

logger = logging.getLogger(__name__)


class SweepScheduler:
    def __init__(self, session_factory, run_jobs_fn=run_jobs, interval_seconds=300):
        self._factory = session_factory
        self._run_jobs = run_jobs_fn
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self):
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="sla-sweep-scheduler")

    async def stop(self):
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self):
        while not self._stop.is_set():
            await self._tick()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)

    async def _tick(self):
        try:
            async with leader_lease(SWEEP_LOCK) as lease:
                # Q151：花钱/写下游前先在 PG 认领本 tick（短事务先提交）；若已被
                # 更大 fence 的新 leader 认领，本轮直接放弃，不做任何作业。
                if lease.fence is not None:
                    async with self._factory() as claim_session:
                        outcome = await claim_tick(
                            claim_session,
                            SWEEP_LOCK,
                            lease.fence,
                            lease.owner_token,
                        )
                        if outcome == TICK_LOST:
                            logger.warning(
                                "sweep tick skipped: tick claim held by a newer fence"
                            )
                            return
                        await claim_session.commit()

                async def commit_guard(session) -> bool:
                    return await fence_current(session, SWEEP_LOCK, lease.fence)

                # Q139：checkpoint 在每作业开始前检查锁是否仍持有；Q151：
                # commit_guard 在每作业提交前做 PG 行级 fence 条件更新。
                report = await self._run_jobs(
                    self._factory,
                    checkpoint=lease.raise_if_lost,
                    commit_guard=commit_guard,
                )
                logger.info("sweep tick completed: %s", report)
        except LockUnavailable:
            # 另一副本正在跑：正常，下个周期再试。
            logger.debug("sweep tick skipped: another replica holds the lock")
        except LockLost:
            # Q139/Q151：锁中途易主或提交前门关闭，本轮协作中止，下轮重新抢锁。
            logger.warning("sweep tick aborted mid-run: leader lock lost")
        except LockBackendError:
            # Redis 不可用：fail-closed 跳过本轮，避免无锁并发 sweep。
            logger.warning("sweep tick skipped: lock backend unavailable")
