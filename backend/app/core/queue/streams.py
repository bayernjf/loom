"""Q134 Redis Streams 每信号行细粒度认领原语（docs/07 §7.5 的 V2 队列底座）。

V1 裁决（Q87，docs/07 §7.5）：restock worker 用进程内轮询 + DB 反连接认领，
单实例 leader 锁防双花。水平并行消费（多副本各消费一部分信号行、崩溃行被别的
副本接走）后置 V2，本模块只落 Streams 原语，**不切换 worker 主路径、不建占位
端点、不落 env 开关**——V2 接入方（restock/未来异步任务）再按本包语义接线。

原语映射 Redis Streams 消费组语义：
- 生产 ``XADD``（近似 MAXLEN 裁剪，边界保护）；
- ``XGROUP CREATE`` 幂等建组（BUSYGROUP 忽略，mkstream 自动建流）；
- 新消息 ``XREADGROUP ... >``：投递即入该组 PEL（pending entries list），
  未 ACK 不会再作为新消息投给同组其他消费者；
- 处理完 ``XACK``；
- 崩溃恢复 ``XPENDING``(idle 过滤) + ``XCLAIM``：把空闲超阈值、原消费者未 ACK
  的行转给本消费者，投递计数 +1；
- 超过最大投递次数的行进死信流并 ACK（``move_to_dead``），避免无限重投。

Redis 故障统一抛 StreamBackendError（fail-closed，调用方跳过本轮，同 Q89 锁口径）。
"""

import contextlib
import logging

import redis
import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# restock requested 信号主流 / 消费组 / 超限死信流。
RESTOCK_STREAM = "loom:stream:restock"
RESTOCK_GROUP = "restock-workers"
RESTOCK_DEAD_STREAM = "loom:stream:restock:dead"

# 死信字段里标注死因与原条目 id 的保留键（业务 payload 不应占用）。
DEAD_REASON_FIELD = "_dead_reason"
DEAD_ORIGIN_FIELD = "_dead_origin_id"

# V2 接入方默认值：单轮最多认领/回收多少行、崩溃行空闲多久可被接管、最大投递次数。
DEFAULT_COUNT = 20
DEFAULT_MIN_IDLE_MS = 60_000
DEFAULT_MAX_DELIVERIES = 5
DEFAULT_MAXLEN = 10_000


class StreamBackendError(Exception):
    """Streams 后端 Redis 故障（fail-closed：调用方跳过本轮；HTTP 口径 503）。"""


_client: aioredis.Redis | None = None
_test_client: aioredis.Redis | None = None


def override_stream_client(client: aioredis.Redis | None) -> None:
    """测试注入替身 Redis；传 None 还原懒连接。"""
    global _test_client
    _test_client = client


def _get_client() -> aioredis.Redis:
    global _client
    client = _test_client if _test_client is not None else _client
    if client is None:
        # decode_responses：消息字段直接按 str 读写（payload 为 JSON 文本）。
        client = aioredis.from_url(get_settings().redis_dsn, decode_responses=True)
        if _test_client is None:
            _client = client
    return client


def delivery_exhausted(delivery_count: int, max_deliveries: int) -> bool:
    """纯函数：投递计数超过上限即应进死信（max=3 时第 4 次投递为超限）。"""
    return delivery_count > max_deliveries


async def add_event(
    client,
    stream: str,
    fields: dict[str, str],
    *,
    maxlen: int | None = DEFAULT_MAXLEN,
) -> str:
    """XADD 一条消息，返回服务端生成的条目 id；approximate MAXLEN 裁剪防无限增长。"""
    try:
        kwargs = {"id": "*"}
        if maxlen is not None:
            kwargs["maxlen"] = maxlen
            kwargs["approximate"] = True
        return await client.xadd(stream, fields, **kwargs)
    except redis.RedisError as exc:
        raise StreamBackendError(f"xadd {stream} failed: {exc}") from exc


async def ensure_group(
    client, stream: str, group: str, *, start_id: str = "0"
) -> bool:
    """XGROUP CREATE 幂等建组；已存在（BUSYGROUP）返回 False，其余故障抛错。"""
    try:
        await client.xgroup_create(stream, group, id=start_id, mkstream=True)
        return True
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            return False
        raise StreamBackendError(f"xgroup create {stream}/{group} failed: {exc}") from exc
    except redis.RedisError as exc:
        raise StreamBackendError(f"xgroup create {stream}/{group} failed: {exc}") from exc


async def read_new(
    client,
    stream: str,
    group: str,
    consumer: str,
    *,
    count: int = DEFAULT_COUNT,
    block_ms: int | None = None,
) -> list[tuple[str, dict[str, str]]]:
    """XREADGROUP '>'：读本组从未投递过的新消息（读即入 PEL），返回 (id, fields)。"""
    try:
        resp = await client.xreadgroup(
            group,
            consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )
    except redis.RedisError as exc:
        raise StreamBackendError(f"xreadgroup {stream}/{group} failed: {exc}") from exc
    return _flatten(resp)


async def reclaim_pending(
    client,
    stream: str,
    group: str,
    consumer: str,
    *,
    min_idle_ms: int = DEFAULT_MIN_IDLE_MS,
    count: int = DEFAULT_COUNT,
) -> list[tuple[str, dict[str, str], int]]:
    """回收崩溃消费者遗留的 pending 行（XPENDING idle 过滤 + XCLAIM）。

    返回 (id, fields, delivery_count)，delivery_count 为接管后的累计投递次数
    （原 times_delivered + 1）。无 idle 超时行时返回空。
    """
    try:
        pending = await client.xpending_range(
            stream, group, "0", "+", count, idle=min_idle_ms
        )
        if not pending:
            return []
        ids = [item["message_id"] for item in pending]
        claimed = await client.xclaim(
            stream, group, consumer, min_idle_ms, ids
        )
        times = {item["message_id"]: int(item.get("times_delivered", 0)) for item in pending}
    except redis.RedisError as exc:
        raise StreamBackendError(f"xclaim {stream}/{group} failed: {exc}") from exc
    return [
        (entry_id, fields, times.get(entry_id, 0) + 1)
        for entry_id, fields in claimed
    ]


async def ack_event(client, stream: str, group: str, *entry_ids: str) -> int:
    """XACK：处理成功后移出 PEL，返回实际确认条数。"""
    if not entry_ids:
        return 0
    try:
        return int(await client.xack(stream, group, *entry_ids))
    except redis.RedisError as exc:
        raise StreamBackendError(f"xack {stream}/{group} failed: {exc}") from exc


async def move_to_dead(
    client,
    stream: str,
    group: str,
    dead_stream: str,
    entry_id: str,
    fields: dict[str, str],
    reason: str,
    *,
    maxlen: int | None = DEFAULT_MAXLEN,
) -> tuple[str, int]:
    """超限行进死信流（附原因/原 id）后 ACK 原流，返回 (死信条目 id, ack 数)。"""
    dead_fields = {**fields, DEAD_REASON_FIELD: reason, DEAD_ORIGIN_FIELD: entry_id}
    dead_id = await add_event(client, dead_stream, dead_fields, maxlen=maxlen)
    acked = await ack_event(client, stream, group, entry_id)
    logger.error(
        "stream entry %s moved to dead-letter %s after %s",
        entry_id,
        dead_stream,
        reason,
    )
    return dead_id, acked


def _flatten(resp) -> list[tuple[str, dict[str, str]]]:
    """规范化 XREADGROUP/XREAD 返回（[(stream, [(id, fields), ...]), ...]）为单流列表。"""
    out: list[tuple[str, dict[str, str]]] = []
    if not resp:
        return out
    for _stream, entries in resp:
        with contextlib.suppress(ValueError):
            out.extend((entry_id, dict(fields)) for entry_id, fields in entries)
    return out
