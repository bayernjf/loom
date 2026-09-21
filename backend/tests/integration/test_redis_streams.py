"""Q134 Redis Streams 细粒度认领原语集成测试（内存 FakeStreamsRedis）。

口径（02 C1.78，推荐甲案）：只落原语不接 worker 主路径（docs/07 §7.5 V1=DB
轮询）。覆盖 XADD 递增 id/MAXLEN 裁剪、XGROUP 幂等建组、XREADGROUP '>' 读即入
PEL、XACK 移出、XPENDING+XCLAIM 崩溃接管与投递计数、idle 过滤、死信流、消费组
隔离、Redis 故障 fail-closed。无真 Redis。
"""

import pytest
import pytest_asyncio
import redis

from app.core.queue import (
    RESTOCK_DEAD_STREAM,
    RESTOCK_GROUP,
    RESTOCK_STREAM,
    StreamBackendError,
    ack_event,
    add_event,
    delivery_exhausted,
    ensure_group,
    move_to_dead,
    override_stream_client,
    read_new,
    reclaim_pending,
)
from app.core.queue import streams as streams_mod
from tests.integration.stream_fakes import FakeStreamsRedis


@pytest_asyncio.fixture
def fake():
    redis_client = FakeStreamsRedis()
    override_stream_client(redis_client)
    yield redis_client
    override_stream_client(None)


@pytest_asyncio.fixture
def failing():
    redis_client = FakeStreamsRedis(fail=True)
    override_stream_client(redis_client)
    yield redis_client
    override_stream_client(None)


def _client():
    return streams_mod._get_client()


# ---------- 纯函数 ----------

async def test_delivery_exhausted_threshold():
    assert delivery_exhausted(1, 3) is False
    assert delivery_exhausted(3, 3) is False  # 达上限仍再给一次
    assert delivery_exhausted(4, 3) is True  # 超过上限才进死信


# ---------- 生产 / 建组 ----------

async def test_add_event_monotonic_ids_and_maxlen(fake):
    ids = [
        await add_event(_client(), RESTOCK_STREAM, {"request_id": str(i)})
        for i in range(5)
    ]
    assert ids == ["1-0", "2-0", "3-0", "4-0", "5-0"]

    capped = FakeStreamsRedis()
    override_stream_client(capped)
    for i in range(5):
        await add_event(capped, RESTOCK_STREAM, {"request_id": str(i)}, maxlen=3)
    assert [eid for eid, _ in capped.streams[RESTOCK_STREAM]] == ["3-0", "4-0", "5-0"]


async def test_ensure_group_idempotent_and_mkstream(fake):
    created = await ensure_group(_client(), RESTOCK_STREAM, RESTOCK_GROUP)
    assert created is True
    assert RESTOCK_STREAM in fake.streams  # mkstream 自动建空流
    again = await ensure_group(_client(), RESTOCK_STREAM, RESTOCK_GROUP)
    assert again is False  # BUSYGROUP 幂等忽略


# ---------- 新消息认领 / ACK ----------

async def test_read_new_delivers_once_into_pel_then_empty(fake):
    await ensure_group(_client(), RESTOCK_STREAM, RESTOCK_GROUP)
    await add_event(_client(), RESTOCK_STREAM, {"request_id": "r1"})
    await add_event(_client(), RESTOCK_STREAM, {"request_id": "r2"})

    first = await read_new(_client(), RESTOCK_STREAM, RESTOCK_GROUP, "c1", count=10)
    assert [fields["request_id"] for _, fields in first] == ["r1", "r2"]
    # 未 ACK：再读新消息为空（已在 PEL，不作为 '>' 重投）。
    assert await read_new(_client(), RESTOCK_STREAM, RESTOCK_GROUP, "c2", count=10) == []
    # ACK 第一条后移出 PEL，新消息读仍为空（不是 pending 拉取）。
    acked = await ack_event(_client(), RESTOCK_STREAM, RESTOCK_GROUP, first[0][0])
    assert acked == 1
    assert await read_new(_client(), RESTOCK_STREAM, RESTOCK_GROUP, "c2") == []


async def test_groups_are_isolated(fake):
    await add_event(_client(), RESTOCK_STREAM, {"request_id": "r1"})
    await ensure_group(_client(), RESTOCK_STREAM, "g-a")
    await ensure_group(_client(), RESTOCK_STREAM, "g-b")
    a = await read_new(_client(), RESTOCK_STREAM, "g-a", "ca", count=10)
    b = await read_new(_client(), RESTOCK_STREAM, "g-b", "cb", count=10)
    assert len(a) == 1 and len(b) == 1  # 两个组各自消费到同一条


# ---------- 崩溃接管 / 死信 ----------

async def test_reclaim_pending_after_crash_with_delivery_count(fake):
    await ensure_group(_client(), RESTOCK_STREAM, RESTOCK_GROUP)
    await add_event(_client(), RESTOCK_STREAM, {"request_id": "r1"})
    delivered = await read_new(_client(), RESTOCK_STREAM, RESTOCK_GROUP, "crashed-a")
    entry_id = delivered[0][0]

    # c1 刚投递、空闲不足：大 min_idle 不接管。
    assert (
        await reclaim_pending(
            _client(), RESTOCK_STREAM, RESTOCK_GROUP, "c1", min_idle_ms=3_600_000
        )
    ) == []
    # 空闲阈值 0：崩溃行被 c1 接管，投递计数 2，字段一致。
    reclaimed = await reclaim_pending(
        _client(), RESTOCK_STREAM, RESTOCK_GROUP, "c1", min_idle_ms=0
    )
    assert len(reclaimed) == 1
    rid, fields, deliveries = reclaimed[0]
    assert rid == entry_id
    assert fields["request_id"] == "r1"
    assert deliveries == 2
    # 已转给 c1：原消费者不再持有（PEL 项 consumer 变更）。
    assert fake.groups[(RESTOCK_STREAM, RESTOCK_GROUP)]["pel"][entry_id]["consumer"] == "c1"


async def test_exhausted_entry_moves_to_dead_letter(fake):
    await ensure_group(_client(), RESTOCK_STREAM, RESTOCK_GROUP)
    await add_event(_client(), RESTOCK_STREAM, {"request_id": "poison"})
    delivered = await read_new(_client(), RESTOCK_STREAM, RESTOCK_GROUP, "c1")
    entry_id, fields = delivered[0]

    # 第 2、3 次投递（两次崩溃接管），max_deliveries=2 → 第 3 次为超限。
    await reclaim_pending(_client(), RESTOCK_STREAM, RESTOCK_GROUP, "c2", min_idle_ms=0)
    third = await reclaim_pending(
        _client(), RESTOCK_STREAM, RESTOCK_GROUP, "c3", min_idle_ms=0
    )
    _, _, deliveries = third[0]
    assert deliveries == 3
    assert delivery_exhausted(deliveries, 2) is True

    dead_id, acked = await move_to_dead(
        _client(),
        RESTOCK_STREAM,
        RESTOCK_GROUP,
        RESTOCK_DEAD_STREAM,
        entry_id,
        fields,
        reason="max-deliveries-exceeded",
    )
    assert acked == 1
    assert entry_id not in fake.groups[(RESTOCK_STREAM, RESTOCK_GROUP)]["pel"]
    dead_entries = fake.streams[RESTOCK_DEAD_STREAM]
    assert dead_entries[0][0] == dead_id
    dead_fields = dead_entries[0][1]
    assert dead_fields["request_id"] == "poison"
    assert dead_fields["_dead_reason"] == "max-deliveries-exceeded"
    assert dead_fields["_dead_origin_id"] == entry_id


# ---------- fail-closed ----------

async def test_backend_failures_are_wrapped(failing):
    client = _client()
    with pytest.raises(StreamBackendError):
        await add_event(client, RESTOCK_STREAM, {"x": "1"})
    with pytest.raises(StreamBackendError):
        await ensure_group(client, RESTOCK_STREAM, RESTOCK_GROUP)


# ---------- Q157：XREAD BLOCK 到期无消息（真 redis-py 行为，替身测不到） ----------

class _XReadTimeoutClient:
    """xreadgroup 固定抛指定异常的最小 client。"""

    def __init__(self, exc):
        self._exc = exc

    async def xreadgroup(self, *args, **kwargs):
        raise self._exc


async def test_read_new_block_timeout_returns_empty():
    # redis-py 用 asyncio.timeout() 实现 XREAD BLOCK：到期无消息抛内置
    # TimeoutError（非 redis.RedisError 子类），语义即"本轮无新消息"。
    client = _XReadTimeoutClient(TimeoutError())
    assert await read_new(
        client, RESTOCK_STREAM, RESTOCK_GROUP, "c", block_ms=5_000
    ) == []


async def test_read_new_nonblock_timeout_is_backend_error():
    # 非 block 读取不应超时，内置 TimeoutError 按后端故障 fail-closed。
    client = _XReadTimeoutClient(TimeoutError())
    with pytest.raises(StreamBackendError):
        await read_new(client, RESTOCK_STREAM, RESTOCK_GROUP, "c", block_ms=None)


async def test_read_new_redis_block_timeout_returns_empty():
    # redis 8.1.0 实测：XREAD BLOCK 到期被包装成 redis.exceptions.TimeoutError
    # （"Timeout reading from redis"，RedisError 子类、非内置 TimeoutError 子类）。
    # block 模式同样是"无消息"而非后端故障，必须返回空而不是 tick skipped。
    client = _XReadTimeoutClient(redis.exceptions.TimeoutError())
    assert await read_new(
        client, RESTOCK_STREAM, RESTOCK_GROUP, "c", block_ms=5_000
    ) == []


async def test_read_new_redis_nonblock_timeout_is_backend_error():
    # 非 block 读取遇到 redis.exceptions.TimeoutError 仍按后端故障 fail-closed。
    client = _XReadTimeoutClient(redis.exceptions.TimeoutError())
    with pytest.raises(StreamBackendError):
        await read_new(client, RESTOCK_STREAM, RESTOCK_GROUP, "c", block_ms=None)
