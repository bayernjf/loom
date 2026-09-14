"""进程内定时调度器：固定间隔跑全部 SLA sweep 作业。

V1 单进程模块化单体（14 §2）；多副本下的分布式锁/单实例触发随部署形态补（挂账）。
"""

import asyncio
import contextlib
import logging

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

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            try:
                report = await self._run_jobs(self._factory)
                if any("error" in r for r in report.values()):
                    logger.warning("scheduled sweep reported errors: %s", report)
            except Exception:
                logger.exception("scheduled sweep failed")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
