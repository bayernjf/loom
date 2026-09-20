"""Q133 fencing token 集成测试：leader_lease 单调令牌 + 租约丢失协作中止。

口径（02 C1.77，推荐甲案）：开启多副本锁后，每次抢锁成功由 Redis INCR 取一把
按锁名全局单调递增的 fence token；INCR 失败 fail-closed 并释放刚取得的锁；
看门狗发现锁中途易主或续约期 Redis 故障，把 lease 置 lost（raise_if_lost 抛
LockLost）。未开启锁时 fence=None、恒 held，且 leader_lock 仍 yield 字面 False
（Q89 向后兼容）。无真 Redis——内存替身实现 set/incr/eval 三条原语。
"""

import asyncio

import pytest
import pytest_asyncio
import redis

from app.core.db import settings
from app.core.locking import (
    SWEEP_LOCK,
    LockBackendError,
    LockLease,
    LockLost,
    leader_lease,
    leader_lock,
    override_lock_client,
)
from app.core.locking import service as lock_service

_RELEASE_LUA = lock_service._RELEASE_LUA
_RENEW_LUA = lock_service._RENEW_LUA
_FENCE_KEY = lock_service._fence_key(SWEEP_LOCK)


class FencingRedis:
    """只实现 fencing 租约用到的 set(NX PX)/incr/eval(释放/续约) 的内存替身。"""

    def __init__(self, *, incr_fail: bool = False, renew_fail: bool = False):
        self.store: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.renewals = 0
        self.incr_fail = incr_fail
        self.renew_fail = renew_fail

    async def set(self, key, value, nx=False, px=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def incr(self, key):
        if self.incr_fail:
            raise redis.RedisError("boom-incr")
        value = self.counters.get(key, 0) + 1
        self.counters[key] = value
        self.store[key] = str(value)  # 真实 INCR 会创建键
        return value

    async def eval(self, script, numkeys, key, token, *args):
        if script == _RELEASE_LUA:
            if self.store.get(key) != token:
                return 0
            self.store.pop(key, None)
            return 1
        if script == _RENEW_LUA:
            if self.renew_fail:
                raise redis.RedisError("boom-renew")
            if self.store.get(key) != token:
                return 0
            self.renewals += 1
            return 1
        raise AssertionError("unexpected lua script")


@pytest_asyncio.fixture
def fencing(monkeypatch):
    fake = FencingRedis()
    monkeypatch.setattr(settings, "distributed_lock_enabled", True)
    override_lock_client(fake)
    yield fake
    override_lock_client(None)


@pytest_asyncio.fixture
def fencing_incr_fail(monkeypatch):
    fake = FencingRedis(incr_fail=True)
    monkeypatch.setattr(settings, "distributed_lock_enabled", True)
    override_lock_client(fake)
    yield fake
    override_lock_client(None)


@pytest_asyncio.fixture
def fencing_renew_fail(monkeypatch):
    fake = FencingRedis(renew_fail=True)
    monkeypatch.setattr(settings, "distributed_lock_enabled", True)
    override_lock_client(fake)
    yield fake
    override_lock_client(None)


# ---------- 门控关闭：零依赖、向后兼容 ----------

async def test_disabled_lease_has_no_fence_and_holds():
    async with leader_lease(SWEEP_LOCK) as lease:
        assert isinstance(lease, LockLease)
        assert lease.fence is None
        assert lease.held is True
        assert bool(lease) is True
        lease.raise_if_lost()  # 不抛


async def test_leader_lock_disabled_still_yields_false():
    # Q89 布尔语义字面保持：未开启锁 yield False（既有调用与测试依赖）。
    async with leader_lock(SWEEP_LOCK) as acquired:
        assert acquired is False


# ---------- fence 单调递增 ----------

async def test_fence_monotonic_across_reacquisitions(fencing):
    async with leader_lease(SWEEP_LOCK) as first:
        assert first.fence == 1
        assert fencing.store[SWEEP_LOCK] == first.owner_token
    # 释放后锁键清空，但 fence 序列保留（不设 TTL、不回绕）。
    assert SWEEP_LOCK not in fencing.store
    assert fencing.store[_FENCE_KEY] == "1"

    async with leader_lease(SWEEP_LOCK) as second:
        assert second.fence == 2
    assert fencing.counters[_FENCE_KEY] == 2


async def test_each_lock_name_has_independent_fence_sequence(fencing):
    from app.core.locking import RESTOCK_LOCK

    async with leader_lease(SWEEP_LOCK) as sweep, leader_lease(RESTOCK_LOCK) as restock:
        assert sweep.fence == 1
        assert restock.fence == 1  # 不同锁名各自从 1 起
    assert fencing.counters[lock_service._fence_key(SWEEP_LOCK)] == 1
    assert fencing.counters[lock_service._fence_key(RESTOCK_LOCK)] == 1


# ---------- fail-closed ----------

async def test_fence_allocation_failure_is_fail_closed(fencing_incr_fail):
    with pytest.raises(LockBackendError):
        async with leader_lease(SWEEP_LOCK):
            pass
    # SET 已成功但 INCR 失败：锁必须被释放，不留残留持锁。
    assert SWEEP_LOCK not in fencing_incr_fail.store


async def test_lease_marked_lost_when_key_expires_mid_tick(fencing):
    async with leader_lease(SWEEP_LOCK, ttl_seconds=0.06) as lease:
        assert lease.held is True
        # 模拟 TTL 到期后锁消失（尚未易主）：续约返回 0。
        fencing.store.pop(SWEEP_LOCK, None)
        await asyncio.sleep(0.14)
        assert lease.held is False
        assert bool(lease) is False
        with pytest.raises(LockLost):
            lease.raise_if_lost()
        # wait_lost 立即返回（不再挂起）。
        await asyncio.wait_for(lease.wait_lost(), timeout=0.1)
    # fence 序列不随锁丢失而清。
    assert fencing.counters[_FENCE_KEY] == 1


async def test_lease_marked_lost_when_renewal_backend_errors(fencing_renew_fail):
    async with leader_lease(SWEEP_LOCK, ttl_seconds=0.06) as lease:
        await asyncio.sleep(0.14)
        # 续约期 Redis 故障无法确认仍持锁：fail-closed 置 lost。
        assert lease.held is False
        with pytest.raises(LockLost):
            lease.raise_if_lost()


async def test_new_owner_gets_strictly_higher_fence(fencing):
    async with leader_lease(SWEEP_LOCK, ttl_seconds=0.06) as old:
        old_fence = old.fence
        # 旧持有者停顿超过 TTL，锁过期被释放并由新副本抢到。
        fencing.store.pop(SWEEP_LOCK, None)
        await asyncio.sleep(0.14)
        assert old.held is False

        async with leader_lease(SWEEP_LOCK) as new:
            assert new.fence > old_fence
            assert old_fence == 1
            assert new.fence == 2
