"""进程内定时调度器：固定间隔跑全部 SLA sweep 作业。

V1 单进程模块化单体（14 §2）；多副本部署开启 LOOM_DISTRIBUTED_LOCK_ENABLED
后每轮 tick 抢 Redis leader 锁（Q89），只有持锁副本跑该轮。
"""

import asyncio
import contextlib
import logging

from app.core.locking import (
    SWEEP_LOCK,
    LockBackendError,
    LockUnavailable,
    leader_lock,
)

logger = logging.getLogger(__name__)


class SweepScheduler:
    def __init__(self, session_factory, run_jobs, interval_seconds: float):
        self._factory = session_factory
        self._run_jobs = run_jobs
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="loom-sweep-scheduler")

    async def _tick(self) -> None:
        """跑一轮 sweep；多副本下非持锁副本/Redis 故障均跳过（Q89）。"""
        try:
            async with leader_lock(SWEEP_LOCK):
                report = await self._run_jobs(self._factory)
        except LockUnavailable:
            logger.info("sweep tick skipped: leader lock held by another replica")
            return
        except LockBackendError:
            logger.exception("sweep tick skipped: lock backend unavailable")
            return
        if any("error" in r for r in report.values()):
            logger.warning("scheduled sweep reported errors: %s", report)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            try:
                await self._tick()
            except Exception:
                logger.exception("scheduled sweep failed")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
