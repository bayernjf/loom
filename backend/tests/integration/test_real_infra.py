"""Q154 真 Redis / 真 PG 多副本锁易主→中止/拒写集成验证（默认 skip，C1.98）。

默认全部 skip：CI 与日常本地跑（无真容器、不设 env）零外部依赖、绝不 fail。
显式提供以下 env 才跑对应一组（一次性 docker 容器，见 docs/17）：

- ``LOOM_TEST_REAL_PG_DSN=postgresql+asyncpg://loom:loom@localhost:55433/loom``
- ``LOOM_TEST_REAL_REDIS_URL=redis://localhost:6380/0``

为什么需要这一片：Q133/Q134/Q135/Q143/Q151 的既有测试全用内存替身
（FencingRedis / FakeStreamsRedis / FakeBroadcastRedis），两套 PG fencing 用
sqlite 单连接以「顺序预置更大 fence」复现易主。替身覆盖不了：

1. 真 PG 两个**独立连接/连接池**之间的提交可见性，以及条件 UPDATE 的行级锁
   在真并发下的串行化（一个事务持行锁未提交时，另一连接的同行 UPDATE 必须阻塞）；
2. 真 Redis 的 SET NX PX 互斥、INCR 单调、Lua 续约/安全释放的原生语义；
3. 真 Redis Streams 消费组 ``XREADGROUP '>'`` 跨 consumer 分片、``XCLAIM``
   崩溃接管与投递计数、死信流；
4. 真 Redis pub/sub 跨连接的失效消息投递（订阅须先建立，消息不持久、易丢）。

本片只验证生产原语在真基础设施上的行为，**不改任何生产代码、不改多副本族 env
默认关闭的纪律**；命名空间一律带 uuid 并在收尾删除，可对同一容器反复跑。
"""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 经 main 的导入链注册全量 ORM 模型（create_all 两 fence 表时 metadata 齐全）。
import app.main  # noqa: F401
from app.core.config_center.broadcast import (
    CONFIG_INVALIDATION_CHANNEL,
    ConfigBroadcastSubscriber,
    override_broadcast_client,
)
from app.core.config_center.cache import config_cache
from app.core.db import Base, settings
from app.core.locking import (
    LockLost,
    LockUnavailable,
    leader_lease,
    override_lock_client,
)
from app.core.locking import service as lock_service
from app.core.queue.streams import (
    ack_event,
    add_event,
    ensure_group,
    move_to_dead,
    override_stream_client,
    read_new,
    reclaim_pending,
)
from app.core.restock.fencing import (
    CLAIM_ACQUIRED,
    CLAIM_LOST,
    claim_request,
)
from app.core.restock.fencing import (
    fence_current as restock_gate,
)
from app.core.restock.models import RestockClaim
from app.core.sla.fencing import (
    TICK_ACQUIRED,
    TICK_LOST,
    claim_tick,
)
from app.core.sla.fencing import (
    fence_current as tick_gate,
)
from app.core.sla.models import SweepTickClaim

PG_DSN = os.getenv("LOOM_TEST_REAL_PG_DSN")
REDIS_URL = os.getenv("LOOM_TEST_REAL_REDIS_URL")

requires_pg = pytest.mark.skipif(
    not PG_DSN, reason="set LOOM_TEST_REAL_PG_DSN (asyncpg DSN) to run real-PG tests"
)
requires_redis = pytest.mark.skipif(
    not REDIS_URL, reason="set LOOM_TEST_REAL_REDIS_URL to run real-Redis tests"
)

# kind → (认领原语, 提交前门, 首次认领返回常量)。
_FENCERS = {
    "restock": (claim_request, restock_gate, CLAIM_ACQUIRED, CLAIM_LOST),
    "sweep": (claim_tick, tick_gate, TICK_ACQUIRED, TICK_LOST),
}


async def _wait_until(predicate, *, timeout: float = 3.0, interval: float = 0.05) -> None:
    """轮询直到 predicate 为真，超时抛 AssertionError（确定性等待真容器副作用）。"""
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met within timeout")


# ---------------------------------------------------------------------------
# 真 PG：跨独立连接的 fence 可见性与行级锁串行化
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pg_factories():
    assert PG_DSN, "LOOM_TEST_REAL_PG_DSN required"
    engine_a = create_async_engine(PG_DSN)
    engine_b = create_async_engine(PG_DSN)  # 独立连接池＝另一个副本
    fence_tables = [RestockClaim.__table__, SweepTickClaim.__table__]
    async with engine_a.begin() as conn:
        # 两 fence 表无业务外键/vector 依赖，可只建这两张，幂等。
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=fence_tables)
        )
    factory_a = async_sessionmaker(engine_a, expire_on_commit=False)
    factory_b = async_sessionmaker(engine_b, expire_on_commit=False)
    try:
        yield factory_a, factory_b
    finally:
        async with engine_a.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.drop_all(sync_conn, tables=fence_tables)
            )
        await engine_a.dispose()
        await engine_b.dispose()


@requires_pg
@pytest.mark.parametrize("kind", ["restock", "sweep"])
async def test_real_pg_cross_connection_takeover_and_conditional_update(
    pg_factories, kind
):
    """两独立连接：B 提交更大 fence 后，A 跨连接可见、旧 fence 条件 UPDATE 拒写。"""
    factory_a, factory_b = pg_factories
    claim, gate, acquired, lost = _FENCERS[kind]
    # restock.request_id 为 varchar(36)（生产＝36 字符 uuid1）；用 32 字符 hex
    # 同时满足 restock(36) 与 sweep.lock_name(64) 两列长度约束。
    key = uuid.uuid4().hex

    # 副本 A（连接池 A）短事务认领 fence=1 并提交。
    async with factory_a() as session:
        assert await claim(session, key, 1, "owner-a") == acquired
        await session.commit()

    # 副本 B（独立连接池 B）升级 fence=2 并提交——sqlite 内存每 engine 独立库，
    # 只有真 PG 这类共享库才能让 A 在后续事务里看到 B 的提交。
    async with factory_b() as session:
        assert await claim(session, key, 2, "owner-b") == acquired
        await session.commit()

    # 旧 leader A 的迟到认领判 lost；fence=1 的条件 UPDATE 命中 0 行→门关。
    async with factory_a() as session:
        assert await claim(session, key, 1, "owner-a") == lost
        assert await gate(session, key, 1) is False
        await session.rollback()

    # 新 leader B 的 fence=2 条件 UPDATE 命中 1 行→门开。
    async with factory_b() as session:
        assert await gate(session, key, 2) is True
        await session.commit()


@requires_pg
@pytest.mark.parametrize("kind", ["restock", "sweep"])
async def test_real_pg_row_lock_blocks_concurrent_takeover_until_rollback(
    pg_factories, kind
):
    """A 持条件 UPDATE 行锁未提交时，B 的同行升级必须阻塞；A 回滚后 B 才接管。"""
    factory_a, factory_b = pg_factories
    claim, gate, acquired, _lost = _FENCERS[kind]
    key = uuid.uuid4().hex  # 32 字符，满足 request_id(36)/lock_name(64) 长度约束

    async with factory_a() as session:
        assert await claim(session, key, 1, "owner-a") == acquired
        await session.commit()

    async with factory_a() as session_a:
        # A 进入业务事务：fence_current 的条件 UPDATE 命中该行并持有行级锁，不提交。
        assert await gate(session_a, key, 1) is True

        async def b_takeover():
            async with factory_b() as session_b:
                result = await claim(session_b, key, 2, "owner-b")
                await session_b.commit()
                return result

        b_task = asyncio.create_task(b_takeover())
        # 给 B 足够时间发起同行 UPDATE：A 未提交，它必须排队等行锁。
        done, pending = await asyncio.wait({b_task}, timeout=0.8)
        assert b_task in pending and not done, "B 的同行升级应被 A 未释放的行锁阻塞"

        # A 作业中止回滚、释放行锁（模拟 fence 违例后旧 leader 放弃本轮）。
        await session_a.rollback()
        result = await asyncio.wait_for(b_task, timeout=5.0)
        assert result == acquired

    # 接管落定后，旧 fence 门关（新连接视角）。
    async with factory_b() as session:
        assert await gate(session, key, 1) is False
        await session.rollback()


# ---------------------------------------------------------------------------
# 真 Redis：leader_lease 互斥 / fencing 单调 / 易主置 lost / 安全释放
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def redis_client():
    assert REDIS_URL, "LOOM_TEST_REAL_REDIS_URL required"
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    await client.ping()
    try:
        yield client
    finally:
        await client.aclose()


@requires_redis
async def test_real_redis_lease_mutual_exclusion_and_monotonic_fence(
    redis_client, monkeypatch
):
    monkeypatch.setattr(settings, "distributed_lock_enabled", True)
    override_lock_client(redis_client)
    name = f"loom:test:lock:{uuid.uuid4()}"
    fence_key = lock_service._fence_key(name)
    try:
        await redis_client.delete(name, fence_key)
        async with leader_lease(name, ttl_seconds=10.0) as lease_a:
            assert lease_a.held
            first = lease_a.fence
            assert isinstance(first, int) and first >= 1
            # 同锁第二副本抢不到（SET NX 原生互斥）。
            with pytest.raises(LockUnavailable):
                async with leader_lease(name, ttl_seconds=10.0):
                    pytest.fail("second lease must not be acquired")
        # A 释放（Lua 比对 token）后 B 可获取，INCR 严格单调 +1。
        async with leader_lease(name, ttl_seconds=10.0) as lease_b:
            assert lease_b.fence == first + 1
        # fencing 序列键长期保留、不设 TTL（防回绕破坏单调性）。
        assert await redis_client.ttl(fence_key) == -1
    finally:
        await redis_client.delete(name, fence_key)
        override_lock_client(None)


@requires_redis
async def test_real_redis_lease_marks_lost_after_handover_and_safe_release(
    redis_client, monkeypatch
):
    monkeypatch.setattr(settings, "distributed_lock_enabled", True)
    override_lock_client(redis_client)
    name = f"loom:test:lock:{uuid.uuid4()}"
    fence_key = lock_service._fence_key(name)
    other = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis_client.delete(name, fence_key)
        async with leader_lease(name, ttl_seconds=0.6) as lease_a:
            # 模拟 TTL 过期后另一副本强抢：删旧锁键并以 B 的 token 占位。
            await other.delete(name)
            await other.set(name, "token-b-handover", nx=True, px=10_000)
            # 看门狗每 ttl/3≈0.2s 续约；Lua 发现 token 不匹配→ renewed=0 → mark_lost。
            await _wait_until(lambda: not lease_a.held, timeout=3.0)
            assert lease_a.held is False
            with pytest.raises(LockLost):
                lease_a.raise_if_lost()
        # A 退出时释放 Lua 比对 token 失败（锁已属 B），不得误删新主的锁。
        assert await redis_client.get(name) == "token-b-handover"
    finally:
        await other.aclose()
        await redis_client.delete(name, fence_key)
        override_lock_client(None)


# ---------------------------------------------------------------------------
# 真 Redis Streams：消费组分片 / XACK / XCLAIM 崩溃接管 / 死信
# ---------------------------------------------------------------------------


@requires_redis
async def test_real_redis_streams_shard_reclaim_and_dead_letter(redis_client):
    override_stream_client(redis_client)
    suffix = uuid.uuid4().hex[:12]
    stream = f"loom:test:stream:{suffix}"
    group = f"g-{suffix}"
    dead_stream = f"loom:test:dead:{suffix}"
    try:
        assert await ensure_group(redis_client, stream, group) is True
        for i in range(6):
            await add_event(redis_client, stream, {"seq": str(i)})

        # 两 consumer 用 '>' 分片新消息：各 3 条、互不重叠（读即入各自 PEL）。
        got_c1 = await read_new(redis_client, stream, group, "c1", count=3)
        got_c2 = await read_new(redis_client, stream, group, "c2", count=3)
        ids1 = {eid for eid, _ in got_c1}
        ids2 = {eid for eid, _ in got_c2}
        assert len(ids1) == 3 and len(ids2) == 3
        assert ids1.isdisjoint(ids2)

        # c1 正常处理完 XACK。
        assert await ack_event(redis_client, stream, group, *ids1) == 3

        # c2 崩溃未 ACK：c3 经 XPENDING(idle=0)+XCLAIM 接管，投递计数升到 2。
        reclaimed = await reclaim_pending(
            redis_client, stream, group, "c3", min_idle_ms=0
        )
        assert len(reclaimed) == 3
        assert {eid for eid, _, _ in reclaimed} == ids2
        assert all(deliveries == 2 for _, _, deliveries in reclaimed)

        # 接管后其中一条判定超限进死信流，并从原流 PEL ACK 移除。
        entry_id, fields = reclaimed[0][0], reclaimed[0][1]
        dead_id, acked = await move_to_dead(
            redis_client, stream, group, dead_stream, entry_id, fields,
            reason="max-deliveries-exceeded",
        )
        assert acked == 1
        dead_rows = await redis_client.xrange(dead_stream)
        assert len(dead_rows) == 1
        assert dead_rows[0][0] == dead_id
        assert dead_rows[0][1]["_dead_origin_id"] == entry_id
        assert dead_rows[0][1]["_dead_reason"] == "max-deliveries-exceeded"
        pending = await redis_client.xpending_range(stream, group, "-", "+", 100)
        assert entry_id not in {item["message_id"] for item in pending}
        # 其余两条仍在 c3 的 PEL（未 ACK）。
        assert len(pending) == 2
    finally:
        await redis_client.delete(stream, dead_stream)
        override_stream_client(None)


# ---------------------------------------------------------------------------
# 真 Redis pub/sub：跨连接失效广播真实投递并触发 reload
# ---------------------------------------------------------------------------


class _DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _dummy_factory():
    return _DummySession()


@requires_redis
async def test_real_redis_pubsub_invalidation_is_delivered_and_reloads(
    redis_client, monkeypatch
):
    override_broadcast_client(redis_client)
    publisher = aioredis.from_url(REDIS_URL, decode_responses=True)
    reloads = 0

    async def fake_reload(*_args):
        nonlocal reloads
        reloads += 1

    # wildcard 走全量 reload；本片只验证真 pub/sub 投递，reload 体用计数替身。
    monkeypatch.setattr(config_cache, "reload", fake_reload)
    monkeypatch.setattr(config_cache, "reload_keys", fake_reload)
    subscriber = ConfigBroadcastSubscriber(
        session_factory=_dummy_factory, poll_timeout_seconds=0.1
    )
    try:
        await subscriber.start()
        await asyncio.sleep(0.5)  # 等真订阅在服务端注册（pub/sub 消息不持久）
        delivered = await publisher.publish(CONFIG_INVALIDATION_CHANNEL, "*")
        assert delivered >= 1, "订阅应已建立，发布至少投递给 1 个订阅者"
        await _wait_until(lambda: subscriber.reloads >= 1, timeout=3.0)
        assert reloads >= 1
    finally:
        await subscriber.stop()
        await publisher.aclose()
        override_broadcast_client(None)
