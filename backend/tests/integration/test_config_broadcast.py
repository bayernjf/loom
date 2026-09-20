"""Q135 配置缓存多副本失效广播集成测试（内存 FakeRedis pub/sub）。

口径（02 C1.79，推荐甲案）：门控 LOOM_CONFIG_CACHE_BROADCAST_ENABLED 默认关、
不接触 Redis；开启后配置事务 after_commit 经 fire-and-forget 任务 PUBLISH 失效
消息（best-effort，发布失败只告警不影响已提交事务）；ConfigBroadcastSubscriber
收到消息后全量 reload，订阅/轮询故障只告警自愈、任务不自毁。无真 Redis。
"""

import asyncio

import pytest_asyncio
import redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config_center import service as config_service
from app.core.config_center.broadcast import (
    CONFIG_INVALIDATION_CHANNEL,
    ConfigBroadcastSubscriber,
    override_broadcast_client,
    publish_invalidation,
    spawn_invalidation,
)
from app.core.config_center.cache import config_cache
from app.core.db import Base, settings


class FakePubSub:
    def __init__(self, owner):
        self._owner = owner
        self.channels: set[str] = set()
        self.inbox: list[str] = []

    async def subscribe(self, *channels):
        self.channels.update(channels)

    async def get_message(self, ignore_subscribe_messages=True, timeout=None):
        if self._owner.ps_fail:
            raise redis.RedisError("boom-get-message")
        if self.inbox:
            data = self.inbox.pop(0)
            return {"type": "message", "channel": next(iter(self.channels)), "data": data}
        return None

    async def aclose(self):
        self._owner.pubsubs.discard(self)

    async def close(self):
        await self.aclose()


class FakeBroadcastRedis:
    def __init__(self, *, fail: bool = False, ps_fail: bool = False):
        self.published: list[tuple[str, str]] = []
        self.pubsubs: set[FakePubSub] = set()
        self.fail = fail
        self.ps_fail = ps_fail

    async def publish(self, channel, data):
        if self.fail:
            raise redis.RedisError("boom-publish")
        self.published.append((channel, data))
        count = 0
        for pubsub in list(self.pubsubs):
            if channel in pubsub.channels:
                pubsub.inbox.append(data)
                count += 1
        return count

    def pubsub(self):
        pubsub = FakePubSub(self)
        self.pubsubs.add(pubsub)
        return pubsub


@pytest_asyncio.fixture
def fake():
    client = FakeBroadcastRedis()
    override_broadcast_client(client)
    yield client
    override_broadcast_client(None)


@pytest_asyncio.fixture
def failing_publish():
    client = FakeBroadcastRedis(fail=True)
    override_broadcast_client(client)
    yield client
    override_broadcast_client(None)


@pytest_asyncio.fixture
def failing_subscriber():
    client = FakeBroadcastRedis(ps_fail=True)
    override_broadcast_client(client)
    yield client
    override_broadcast_client(None)


# ---------- 发布侧 ----------

async def test_disabled_spawn_does_not_touch_redis(fake):
    assert settings.config_cache_broadcast_enabled is False
    spawn_invalidation("some.key")
    await asyncio.sleep(0.02)
    assert fake.published == []


async def test_enabled_spawn_publishes_key_and_wildcard(fake, monkeypatch):
    monkeypatch.setattr(settings, "config_cache_broadcast_enabled", True)
    spawn_invalidation("some.key")
    spawn_invalidation(None)
    await asyncio.sleep(0.05)
    assert fake.published == [
        (CONFIG_INVALIDATION_CHANNEL, "some.key"),
        (CONFIG_INVALIDATION_CHANNEL, "*"),
    ]


async def test_publish_failure_is_best_effort_and_swallowed(failing_publish, monkeypatch):
    monkeypatch.setattr(settings, "config_cache_broadcast_enabled", True)
    # after_commit 场景：发布失败不得抛出污染提交方。
    spawn_invalidation("some.key")
    await asyncio.sleep(0.05)
    assert failing_publish.published == []


async def test_after_commit_hook_broadcasts(fake, monkeypatch):
    monkeypatch.setattr(settings, "config_cache_broadcast_enabled", True)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            config_service._schedule_cache_apply(session, "hook.key", 7)
            await session.commit()  # 触发 after_commit → spawn → publish
            await asyncio.sleep(0.05)
        assert (CONFIG_INVALIDATION_CHANNEL, "hook.key") in fake.published
    finally:
        await engine.dispose()


async def test_publish_invalidation_returns_subscriber_count(fake):
    # 无订阅者时返回 0。
    assert await publish_invalidation(fake, key="k") == 0


# ---------- 订阅侧 ----------

class _DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _dummy_factory():
    return _DummySession()


async def test_subscriber_reloads_on_wildcard_invalidation(fake, monkeypatch):
    reloads = 0

    async def fake_reload(session):
        nonlocal reloads
        reloads += 1

    async def fail_reload_keys(session, keys):
        raise AssertionError("wildcard must trigger full reload, not reload_keys")

    monkeypatch.setattr(config_cache, "reload", fake_reload)
    monkeypatch.setattr(config_cache, "reload_keys", fail_reload_keys)
    subscriber = ConfigBroadcastSubscriber(
        session_factory=_dummy_factory, poll_timeout_seconds=0.02
    )
    await subscriber.start()
    try:
        await asyncio.sleep(0.08)  # 等订阅建立
        delivered = await fake.publish(CONFIG_INVALIDATION_CHANNEL, "*")
        assert delivered == 1
        await asyncio.sleep(0.12)  # 等轮询处理
        assert reloads >= 1
        assert subscriber.reloads >= 1
    finally:
        await subscriber.stop()
    assert subscriber.running is False


async def test_subscriber_reloads_single_key_incrementally(fake, monkeypatch):
    reloaded_keys: list[str] = []
    full_reloads = 0

    async def fake_reload_keys(session, keys):
        reloaded_keys.extend(keys)

    async def fail_full_reload(session):
        nonlocal full_reloads
        full_reloads += 1

    monkeypatch.setattr(config_cache, "reload_keys", fake_reload_keys)
    monkeypatch.setattr(config_cache, "reload", fail_full_reload)
    subscriber = ConfigBroadcastSubscriber(
        session_factory=_dummy_factory, poll_timeout_seconds=0.02
    )
    await subscriber.start()
    try:
        await asyncio.sleep(0.08)
        await fake.publish(CONFIG_INVALIDATION_CHANNEL, "some.key")
        await asyncio.sleep(0.12)
        assert reloaded_keys == ["some.key"]
        assert full_reloads == 0  # 单 key 不触发全量 reload
    finally:
        await subscriber.stop()


async def test_poll_failure_backs_off_then_resets(failing_subscriber):
    subscriber = ConfigBroadcastSubscriber(
        session_factory=None, poll_timeout_seconds=0.01,
        backoff_base_seconds=0.01, backoff_cap_seconds=0.05,
    )
    # get_message 抛 RedisError：poll_once 不抛、返回 False，连续故障计数累加。
    assert await subscriber.poll_once() is False
    assert await subscriber.poll_once() is False
    assert subscriber.consecutive_failures == 2
    # 指数退避：第 2 次失败后延迟 base*2^(2-1)=0.02，封顶 0.05。
    assert subscriber._backoff_delay() == 0.02
    # 恢复连接、无消息即视为健康，退避计数重置。
    failing_subscriber.ps_fail = False
    assert await subscriber.poll_once() is False
    assert subscriber.consecutive_failures == 0


async def test_loop_backs_off_instead_of_busy_spinning(monkeypatch):
    # 记录每次 get_message 的时刻；故障 + 退避下两次轮询间隔应≈退避而非 0。
    timestamps: list[float] = []

    class CountingPubSub(FakePubSub):
        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            timestamps.append(asyncio.get_event_loop().time())
            raise redis.RedisError("boom")

    class CountingRedis(FakeBroadcastRedis):
        def pubsub(self):
            ps = CountingPubSub(self)
            self.pubsubs.add(ps)
            return ps

    client = CountingRedis()
    override_broadcast_client(client)
    try:
        subscriber = ConfigBroadcastSubscriber(
            session_factory=None, poll_timeout_seconds=0.0,
            backoff_base_seconds=0.05, backoff_cap_seconds=0.05,
        )
        await subscriber.start()
        await asyncio.sleep(0.18)  # 覆盖至少两次退避间隔
        await subscriber.stop()
    finally:
        override_broadcast_client(None)
    # 无退避忙等会在 0.18s 内轮询成百上千次；有 0.05 退避则次数很少。
    assert len(timestamps) <= 5
    if len(timestamps) >= 2:
        assert timestamps[1] - timestamps[0] >= 0.04


async def test_reload_keys_updates_inserts_and_removes():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config_center.models import ConfigItem

    def _item(key: str, value: int) -> ConfigItem:
        return ConfigItem(
            key=key,
            category="test",
            value=value,
            value_type="int",
            source_ref="test",
        )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            session.add_all([_item("a", 1), _item("b", 2), _item("c", 3)])
            await session.commit()
        async with factory() as session:
            await config_cache.reload(session)
        assert config_cache.get("a") == 1
        assert config_cache.get("b") == 2

        # a 更新、b 删除、新增 d；只对 [a,b,d] 做增量失效。
        async with factory() as session:
            row_a = await session.get(ConfigItem, "a")
            row_a.value = 100
            row_b = await session.get(ConfigItem, "b")
            await session.delete(row_b)
            session.add(_item("d", 4))
            await session.commit()
        async with factory() as session:
            await config_cache.reload_keys(session, ["a", "b", "d"])

        assert config_cache.get("a") == 100  # 更新
        assert config_cache.get("b") is None  # 删除：从快照移除
        assert config_cache.get("c") == 3  # 未涉及：保持旧值
        assert config_cache.get("d") == 4  # 新增
    finally:
        await engine.dispose()


async def test_subscriber_poll_failure_is_self_healing(failing_subscriber):
    subscriber = ConfigBroadcastSubscriber(session_factory=None, poll_timeout_seconds=0.01)
    # get_message 抛 RedisError：poll_once 不抛、返回 False，下轮懒重建订阅。
    assert await subscriber.poll_once() is False
    assert await subscriber.poll_once() is False
