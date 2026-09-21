"""Q151 SLA sweep PG 行级 fencing 认领/提交前门测试（sqlite，C1.95）。

三层覆盖：
1. claim_tick / fence_current 原语（同 Q143 restock 范式，认领粒度＝循环锁名，
   每锁一行）；
2. run_jobs 的 commit_guard：门关闭（锁在作业执行期间易主）时该作业回滚并抛
   LockLost、本轮后续作业不执行；门开时正常提交；
3. scheduler._tick 接线：锁开启时 tick 短事务认领落 sweep_tick_claims 行并把
   commit_guard 传给 runner；认领行已被更大 fence 占有时本轮静默放弃、不跑作业。

fence=None（锁关闭，V1 单副本默认）全程 no-op 的路径由既有 Q89/Q139 测试覆盖。
sqlite 内存库单连接无法在作业事务打开时由另一会话并发提交接管，「作业中途易主」
以顺序预置更大 fence 行的方式确定性复现（边界同 Q143）。
"""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 经 main 的导入链注册全量 ORM 模型，供 Base.metadata.create_all 建齐 FK 依赖表。
import app.main  # noqa: F401
from app.core.db import Base, settings
from app.core.locking import SWEEP_LOCK, LockLost, override_lock_client
from app.core.sla import runner as sla_runner
from app.core.sla.fencing import (
    TICK_ACQUIRED,
    TICK_HELD,
    TICK_LOST,
    claim_tick,
    fence_current,
)
from app.core.sla.models import SweepTickClaim
from app.core.sla.scheduler import SweepScheduler
from tests.integration.test_fencing_lease import FencingRedis


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


@pytest_asyncio.fixture
def fencing(monkeypatch):
    fake = FencingRedis()
    monkeypatch.setattr(settings, "distributed_lock_enabled", True)
    override_lock_client(fake)
    yield fake
    override_lock_client(None)


# ---------- 1. 认领/提交前门原语 ----------


async def test_claim_first_acquires_then_same_fence_held(factory):
    async with factory() as session:
        assert await claim_tick(session, SWEEP_LOCK, 1, "owner-a") == TICK_ACQUIRED
        await session.commit()
    async with factory() as session:
        assert await claim_tick(session, SWEEP_LOCK, 1, "owner-a") == TICK_HELD
        await session.commit()
    async with factory() as session:
        row = await session.get(SweepTickClaim, SWEEP_LOCK)
        assert row.fence == 1
        assert row.claimed_by == "owner-a"


async def test_larger_fence_takes_over_smaller_rejected(factory):
    async with factory() as session:
        await claim_tick(session, SWEEP_LOCK, 1, "owner-a")
        await session.commit()
    # 新 leader（更大 fence）接管认领。
    async with factory() as session:
        assert await claim_tick(session, SWEEP_LOCK, 2, "owner-b") == TICK_ACQUIRED
        await session.commit()
    # 旧 leader 的迟到认领被拒（lost）；新 leader 重入 held。
    async with factory() as session:
        assert await claim_tick(session, SWEEP_LOCK, 1, "owner-a") == TICK_LOST
    async with factory() as session:
        assert await claim_tick(session, SWEEP_LOCK, 2, "owner-b") == TICK_HELD
    async with factory() as session:
        row = await session.get(SweepTickClaim, SWEEP_LOCK)
        assert row.fence == 2
        assert row.claimed_by == "owner-b"


async def test_none_fence_is_noop_and_gate_always_open(factory):
    # fence=None（多副本锁关闭）：认领直接 held、不落行；门恒 True。
    async with factory() as session:
        assert await claim_tick(session, SWEEP_LOCK, None) == TICK_HELD
        await session.commit()
        assert await fence_current(session, SWEEP_LOCK, None) is True
    async with factory() as session:
        rows = list((await session.scalars(select(SweepTickClaim))).all())
        assert rows == []


async def test_fence_current_gate_closes_after_takeover(factory):
    async with factory() as session:
        await claim_tick(session, SWEEP_LOCK, 1, "owner-a")
        await session.commit()
    # 持锁者提交前门命中。
    async with factory() as session:
        assert await fence_current(session, SWEEP_LOCK, 1) is True
        await session.commit()
    # 作业执行期间易主：新 leader 升到 fence=2。
    async with factory() as session:
        await claim_tick(session, SWEEP_LOCK, 2, "owner-b")
        await session.commit()
    # 旧 leader 的条件更新命中 0 行 → 门关闭；新 leader 命中。
    async with factory() as session:
        assert await fence_current(session, SWEEP_LOCK, 1) is False
        await session.rollback()
    async with factory() as session:
        assert await fence_current(session, SWEEP_LOCK, 2) is True
        await session.commit()


# ---------- 2. run_jobs 提交前门 ----------


async def test_run_jobs_commits_when_guard_open(factory, monkeypatch):
    async def j1(session, _now):
        session.add(SweepTickClaim(lock_name="marker", fence=1))
        return 1

    monkeypatch.setattr(sla_runner, "JOBS", [("j1", j1)])

    async with factory() as session:
        assert await claim_tick(session, SWEEP_LOCK, 1, "owner-a") == TICK_ACQUIRED
        await session.commit()

    async def guard(session):
        return await fence_current(session, SWEEP_LOCK, 1)

    report = await sla_runner.run_jobs(factory, commit_guard=guard)
    assert report["j1"] == {"changed": 1}
    async with factory() as session:
        assert await session.get(SweepTickClaim, "marker") is not None


async def test_run_jobs_rolls_back_and_aborts_when_guard_closed(factory, monkeypatch):
    ran: list[str] = []

    async def j1(session, _now):
        # 作业结果（迟到写入）：门关闭时必须随事务回滚。
        session.add(SweepTickClaim(lock_name="marker", fence=1))
        return 1

    async def j2(_session, _now):
        ran.append("j2")
        return 1

    monkeypatch.setattr(sla_runner, "JOBS", [("j1", j1), ("j2", j2)])

    # 旧 leader（fence=1）tick 开始认领。
    async with factory() as session:
        await claim_tick(session, SWEEP_LOCK, 1, "owner-a")
        await session.commit()
    # j1 执行期间易主：新 leader 以 fence=2 接管。
    async with factory() as session:
        await claim_tick(session, SWEEP_LOCK, 2, "owner-b")
        await session.commit()

    async def stale_guard(session):
        return await fence_current(session, SWEEP_LOCK, 1)

    with pytest.raises(LockLost):
        await sla_runner.run_jobs(factory, commit_guard=stale_guard)
    assert ran == []  # j2 本轮不再执行
    async with factory() as session:
        assert await session.get(SweepTickClaim, "marker") is None  # j1 已回滚


# ---------- 3. scheduler._tick 认领接线 ----------


async def test_scheduler_tick_claims_row_and_passes_guard(
    factory, fencing, monkeypatch
):
    seen: dict = {}

    async def fake_run_jobs(_factory, **kwargs):
        seen["commit_guard"] = kwargs.get("commit_guard")
        seen["checkpoint"] = kwargs.get("checkpoint")
        return {}

    monkeypatch.setattr(sla_runner, "JOBS", [])
    scheduler = SweepScheduler(factory, fake_run_jobs, 300.0)
    await scheduler._tick()

    assert seen["commit_guard"] is not None
    assert seen["checkpoint"] is not None
    async with factory() as session:
        row = await session.get(SweepTickClaim, SWEEP_LOCK)
        assert row is not None
        assert row.fence == 1  # FencingRedis 首个 fence


async def test_scheduler_tick_skips_jobs_when_claim_held_by_newer_fence(
    factory, fencing
):
    # 预置更大 fence 的认领行（新 leader 已接管）。
    async with factory() as session:
        session.add(
            SweepTickClaim(lock_name=SWEEP_LOCK, fence=99, claimed_by="new-leader")
        )
        await session.commit()

    called: list[bool] = []

    async def fake_run_jobs(_factory, **_kwargs):
        called.append(True)
        return {}

    scheduler = SweepScheduler(factory, fake_run_jobs, 300.0)
    await scheduler._tick()  # claim LOST 静默放弃，不抛异常
    assert called == []  # 本轮作业一个都不跑
