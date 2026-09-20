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


async def test_subscriber_reloads_on_invalidation(fake, monkeypatch):
    reloads = 0

    async def fake_reload(session):
        nonlocal reloads
        reloads += 1

    monkeypatch.setattr(config_cache, "reload", fake_reload)
    subscriber = ConfigBroadcastSubscriber(
        session_factory=_dummy_factory, poll_timeout_seconds=0.02
    )
    await subscriber.start()
    try:
        await asyncio.sleep(0.08)  # 等订阅建立
        delivered = await fake.publish(CONFIG_INVALIDATION_CHANNEL, "some.key")
        assert delivered == 1
        await asyncio.sleep(0.12)  # 等轮询处理
        assert reloads >= 1
        assert subscriber.reloads >= 1
    finally:
        await subscriber.stop()
    assert subscriber.running is False


async def test_subscriber_poll_failure_is_self_healing(failing_subscriber):
    subscriber = ConfigBroadcastSubscriber(session_factory=None, poll_timeout_seconds=0.01)
    # get_message 抛 RedisError：poll_once 不抛、返回 False，下轮懒重建订阅。
    assert await subscriber.poll_once() is False
    assert await subscriber.poll_once() is False
