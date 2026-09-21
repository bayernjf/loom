"""Q139 两循环 leader_lease 协作中止集成测试。

口径（02 C1.83，推荐甲案）：SLA sweep / restock 两循环与两个手工 /run 端点改用
leader_lease，持锁方在作业/信号之间以 lease.raise_if_lost 为 checkpoint；锁在一轮
中途过期易主时抛 LockLost 协作中止，旧持有者不再写下游/继续花钱。门控关闭时
lease 恒 held、checkpoint 不触发，行为与 Q89 布尔锁一致。

覆盖：run_jobs 作业间 checkpoint 中止、run_restock 信号间 checkpoint 中止、两个
循环 _tick 捕获 LockLost 不冒泡（不拖垮调度循环）。
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.core.db import settings
from app.core.locking import (
    RESTOCK_LOCK,
    SWEEP_LOCK,
    LockLost,
    override_lock_client,
)
from app.core.restock import worker as restock_worker
from app.core.sla import runner as sla_runner
from app.core.sla import scheduler as sla_scheduler
from app.core.sla.fencing import TICK_HELD
from app.core.sla.scheduler import SweepScheduler
from tests.integration.test_fencing_lease import FencingRedis


@pytest_asyncio.fixture
def fencing(monkeypatch):
    fake = FencingRedis()
    monkeypatch.setattr(settings, "distributed_lock_enabled", True)
    override_lock_client(fake)
    yield fake
    override_lock_client(None)


class _FakeSession:
    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


@asynccontextmanager
async def _null_factory():
    yield _FakeSession()


# ---------- run_jobs 作业间 checkpoint ----------


async def test_run_jobs_checkpoint_aborts_before_remaining_jobs(monkeypatch):
    ran: list[str] = []

    async def j1(_session, _now):
        ran.append("j1")
        return 1

    async def j2(_session, _now):
        ran.append("j2")
        return 1

    monkeypatch.setattr(sla_runner, "JOBS", [("j1", j1), ("j2", j2)])

    calls = {"n": 0}

    def checkpoint() -> None:
        calls["n"] += 1
        if calls["n"] == 2:  # j2 开始前锁已易主
            raise LockLost(SWEEP_LOCK)

    with pytest.raises(LockLost):
        await sla_runner.run_jobs(_null_factory, checkpoint=checkpoint)
    assert ran == ["j1"]  # j1 已提交完成，j2 本轮不再执行


async def test_run_jobs_without_checkpoint_runs_all(monkeypatch):
    ran: list[str] = []

    async def j1(_session, _now):
        ran.append("j1")
        return 1

    async def j2(_session, _now):
        ran.append("j2")
        return 1

    monkeypatch.setattr(sla_runner, "JOBS", [("j1", j1), ("j2", j2)])
    report = await sla_runner.run_jobs(_null_factory)
    assert ran == ["j1", "j2"]
    assert set(report) == {"j1", "j2"}


# ---------- run_restock 信号间 checkpoint ----------


async def test_run_restock_checkpoint_aborts_between_signals(monkeypatch):
    requested = [SimpleNamespace(run_id="r1"), SimpleNamespace(run_id="r2")]

    async def fake_claim(_session, _limit, *, now, honor_backoff):
        return requested

    processed: list[str] = []

    async def fake_process(_factory, requested_row, **_kwargs):
        processed.append(requested_row.run_id)
        return {"status": "succeeded"}

    monkeypatch.setattr(restock_worker, "_claim_pending", fake_claim)
    monkeypatch.setattr(restock_worker, "_process_one", fake_process)

    seen = {"n": 0}

    def checkpoint() -> None:
        seen["n"] += 1
        if seen["n"] == 2:  # 第二条信号花钱前锁易主
            raise LockLost(RESTOCK_LOCK)

    with pytest.raises(LockLost):
        await restock_worker.run_restock(_null_factory, checkpoint=checkpoint)
    assert processed == ["r1"]  # 只补了第一条，第二条本轮不花钱


# ---------- 循环 _tick 捕获 LockLost 不冒泡 ----------


async def test_sweep_tick_swallows_lock_lost(fencing, monkeypatch):
    # Q151：factory=object() 不支持 PG 认领，patch 绕过（认领语义见 test_sweep_fencing）。
    async def _claim_held(*_args, **_kwargs):
        return TICK_HELD

    monkeypatch.setattr(sla_scheduler, "claim_tick", _claim_held)

    async def boom(_factory, **_kwargs):
        raise LockLost(SWEEP_LOCK)

    scheduler = SweepScheduler(_null_factory, boom, 300.0)
    await scheduler._tick()  # 不抛：协作中止本轮，循环继续


async def test_restock_tick_swallows_lock_lost(fencing, monkeypatch):
    async def boom(*_args, **_kwargs):
        raise LockLost(RESTOCK_LOCK)

    monkeypatch.setattr(restock_worker, "run_restock", boom)
    worker = restock_worker.RestockWorker(object(), 60.0, 20)
    await worker._tick()  # 不抛：协作中止本轮，循环继续
