"""Q134 Redis Streams 细粒度认领原语（V2 水平并行消费底座）。

V1 不接入 worker 主路径（docs/07 §7.5 裁决 V1=进程内 DB 轮询）；本包只提供
XADD/消费组/XREADGROUP/ACK/XPENDING+XCLAIM 崩溃接管/死信原语，供 V2 restock
等异步任务接入，实现多副本按信号行水平并行消费。默认不连接 Redis、无 env 开关、
无 PG 迁移。
"""

from .streams import (
    DEAD_ORIGIN_FIELD,
    DEAD_REASON_FIELD,
    DEFAULT_COUNT,
    DEFAULT_MAX_DELIVERIES,
    DEFAULT_MAXLEN,
    DEFAULT_MIN_IDLE_MS,
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

__all__ = [
    "DEAD_ORIGIN_FIELD",
    "DEAD_REASON_FIELD",
    "DEFAULT_COUNT",
    "DEFAULT_MAXLEN",
    "DEFAULT_MAX_DELIVERIES",
    "DEFAULT_MIN_IDLE_MS",
    "RESTOCK_DEAD_STREAM",
    "RESTOCK_GROUP",
    "RESTOCK_STREAM",
    "StreamBackendError",
    "ack_event",
    "add_event",
    "delivery_exhausted",
    "ensure_group",
    "move_to_dead",
    "override_stream_client",
    "read_new",
    "reclaim_pending",
]
