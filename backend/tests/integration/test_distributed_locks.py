"""Q89 集成测试：多副本 Redis leader 锁原语 + 两个循环/手工端点抢锁。

口径（02 C1.33）：env 门控默认关；开启后 SET NX PX 互斥、Lua 比对 token
安全释放、看门狗续约；抢不到跳轮（HTTP 409）、Redis 故障 fail-closed
跳轮（HTTP 503）。无真 Redis——内存替身实现 set/eval 两条原语。
"""

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
import redis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session, settings
from app.core.locking import (
    RESTOCK_LOCK,
    SWEEP_LOCK,
    LockBackendError,
    LockUnavailable,
    leader_lock,
    override_lock_client,
)
from app.core.locking import service as lock_service
from app.core.restock.worker import RestockWorker
from app.core.sla.scheduler import SweepScheduler
from app.main import app

PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}

_RELEASE_LUA = lock_service._RELEASE_LUA
_RENEW_LUA = lock_service._RENEW_LUA


class FakeRedis:
    """只实现锁用到的 set(NX PX)/eval(释放/续约) 的内存替身。"""

    def __init__(self, *, fail: bool = False):
        self.store: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.renewals = 0
        self.fail = fail

    async def set(self, key, value, nx=False, px=None):
        if self.fail:
            raise redis.RedisError("boom")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def incr(self, key):
        # Q133 fencing token：按锁名单调递增（失败替身同样抛错走 fail-closed）。
        if self.fail:
            raise redis.RedisError("boom")
        value = self.counters.get(key, 0) + 1
        self.counters[key] = value
        self.store[key] = str(value)
        return value

    async def eval(self, script, numkeys, key, token, *args):
        if self.fail:
            raise redis.RedisError("boom")
        if self.store.get(key) != token:
            return 0
        if script == _RELEASE_LUA:
            self.store.pop(key, None)
            return 1
        if script == _RENEW_LUA:
            self.renewals += 1
            return 1
        raise AssertionError("unexpected lua script")


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def locks_enabled(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(settings, "distributed_lock_enabled", True)
    override_lock_client(fake)
    yield fake
    override_lock_client(None)


@pytest.fixture
def locks_failing(monkeypatch):
    fake = FakeRedis(fail=True)
    monkeypatch.setattr(settings, "distributed_lock_enabled", True)
    override_lock_client(fake)
    yield fake
    override_lock_client(None)


# ---------- 门控与原语 ----------

async def test_disabled_passes_without_locking():
    # 默认关闭：两层嵌套都直接放行，且不触碰 Redis。
    async with leader_lock(SWEEP_LOCK) as outer:
        assert outer is False
        async with leader_lock(SWEEP_LOCK) as inner:
            assert inner is False


async def test_acquire_excludes_second_holder_then_reacquire(locks_enabled):
    async with leader_lock(SWEEP_LOCK):
        assert SWEEP_LOCK in locks_enabled.store
        with pytest.raises(LockUnavailable):
            async with leader_lock(SWEEP_LOCK):
                pass
    assert SWEEP_LOCK not in locks_enabled.store
    async with leader_lock(SWEEP_LOCK):
        assert SWEEP_LOCK in locks_enabled.store


async def test_release_does_not_delete_foreign_token(locks_enabled):
    async with leader_lock(SWEEP_LOCK):
        # TTL 到期易主：别人的 token 覆盖了本锁。
        locks_enabled.store[SWEEP_LOCK] = "someone-else"
    # 释放不得删掉别人的锁。
    assert locks_enabled.store[SWEEP_LOCK] == "someone-else"


async def test_watchdog_renews_before_ttl(locks_enabled):
    async with leader_lock(SWEEP_LOCK, ttl_seconds=0.06):
        token = locks_enabled.store[SWEEP_LOCK]
        await asyncio.sleep(0.14)
        assert locks_enabled.renewals >= 1
        assert locks_enabled.store[SWEEP_LOCK] == token


async def test_renew_lost_when_key_expired_is_swallowed(locks_enabled):
    async with leader_lock(SWEEP_LOCK, ttl_seconds=0.06):
        # 模拟 TTL 到期后锁消失：续约返回 0，看门狗静默退出，上下文不抛。
        locks_enabled.store.clear()
        await asyncio.sleep(0.14)
    assert SWEEP_LOCK not in locks_enabled.store


async def test_backend_failure_on_acquire_is_fail_closed(locks_failing):
    with pytest.raises(LockBackendError):
        async with leader_lock(SWEEP_LOCK):
            pass


# ---------- 循环 tick 抢锁 ----------

async def test_scheduler_tick_runs_when_lock_free(locks_enabled):
    calls = 0

    async def run_jobs(factory, **_kwargs):
        nonlocal calls
        calls += 1
        return {}

    scheduler = SweepScheduler(None, run_jobs, 300.0)
    await scheduler._tick()
    assert calls == 1
    assert SWEEP_LOCK not in locks_enabled.store  # 跑完即放


async def test_scheduler_tick_skips_when_lock_held(locks_enabled):
    calls = 0

    async def run_jobs(factory, **_kwargs):
        nonlocal calls
        calls += 1
        return {}

    locks_enabled.store[SWEEP_LOCK] = "other-replica"
    scheduler = SweepScheduler(None, run_jobs, 300.0)
    await scheduler._tick()
    assert calls == 0


async def test_scheduler_tick_skips_when_backend_down(locks_failing):
    calls = 0

    async def run_jobs(factory, **_kwargs):
        nonlocal calls
        calls += 1
        return {}

    scheduler = SweepScheduler(None, run_jobs, 300.0)
    await scheduler._tick()  # fail-closed，不抛
    assert calls == 0


async def test_restock_tick_skip_and_run(locks_enabled, monkeypatch):
    calls = 0

    async def fake_run_restock(factory, limit, **_kwargs):
        nonlocal calls
        calls += 1
        return {"claimed": 0, "succeeded": 0, "failed": 0, "deferred": 0, "runs": {}}

    monkeypatch.setattr("app.core.restock.worker.run_restock", fake_run_restock)
    worker = RestockWorker(None, 60.0, 20)

    await worker._tick()
    assert calls == 1
    assert RESTOCK_LOCK not in locks_enabled.store

    locks_enabled.store[RESTOCK_LOCK] = "other-replica"
    await worker._tick()
    assert calls == 1  # 被锁跳过，计数不增


# ---------- 手工端点 ----------

async def test_sla_run_lock_states(client, session_factory, locks_enabled):
    resp = await client.post("/api/admin/sla/run", json={"actor": PLATFORM_ADMIN})
    assert resp.status_code == 200

    locks_enabled.store[SWEEP_LOCK] = "other-replica"
    resp = await client.post("/api/admin/sla/run", json={"actor": PLATFORM_ADMIN})
    assert resp.status_code == 409


async def test_restock_run_lock_states(client, session_factory, locks_enabled):
    resp = await client.post("/api/admin/restock/run", json={"actor": PLATFORM_ADMIN})
    assert resp.status_code == 200

    locks_enabled.store[RESTOCK_LOCK] = "other-replica"
    resp = await client.post("/api/admin/restock/run", json={"actor": PLATFORM_ADMIN})
    assert resp.status_code == 409


async def test_manual_runs_503_when_backend_down(client, session_factory, locks_failing):
    for path in ("/api/admin/sla/run", "/api/admin/restock/run"):
        resp = await client.post(path, json={"actor": PLATFORM_ADMIN})
        assert resp.status_code == 503
