"""SweepScheduler 定时循环：到点跑作业、可干净停止（不依赖 DB）。"""

import asyncio

import pytest

from app.core.sla.scheduler import SweepScheduler


class _FakeFactory:
    pass


@pytest.mark.asyncio
async def test_scheduler_runs_jobs_until_stopped():
    calls = 0

    async def fake_run_jobs(factory):
        nonlocal calls
        calls += 1
        return {}

    scheduler = SweepScheduler(_FakeFactory(), fake_run_jobs, interval_seconds=0.01)
    await scheduler.start()
    assert scheduler.running
    await asyncio.sleep(0.05)
    await scheduler.stop()
    assert not scheduler.running
    assert calls >= 1

    # stop 幂等
    await scheduler.stop()
