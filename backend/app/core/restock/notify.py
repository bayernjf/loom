"""Q138 restock requested 信号的 Redis Streams 生产接线（只写侧）。

Q71/Q76-4 跌破 critical 落 ``skill_runs(requested, restock_auto)`` 行后，本模块
在事务 ``after_commit`` 把该 request_id XADD 到 Q134 restock 流（消费组
restock-workers 幂等建组），作为多副本场景下的持久化补货信号 / 唤醒事件。

边界（02 C1.82 拍板）：
- **DB requested 行是唯一事实源**，流是提示/留痕：XADD 一律 best-effort，失败只
  告警，不影响补货请求落库；Q87 进程内 worker 的 DB 反连接认领 + Q90 退避游标仍
  是权威路径，信号不会因 XADD 失败而丢。
- 本批**只接生产侧，不把 worker 主认领路径切到消费组**：restock 会自动花真
  token，Q87/Q89 已裁决由 leader 锁保证单实例防双花，而消费组是多副本水平并行
  语义，二者冲突。水平并行消费（多副本各消费一部分信号行）属 V2 容量决策，需重新
  评估花钱隔离后再按 Q134 原语 + Q137 ExportWorker 范式接入。

门控 ``LOOM_RESTOCK_STREAM_ENABLED`` 默认 false：单副本/本地不接触 Redis，行为
与 Q87 完全一致。无 PG 迁移。
"""

import asyncio
import logging

from app.core.config import get_settings
from app.core.queue import (
    RESTOCK_GROUP,
    RESTOCK_STREAM,
    add_event,
    ensure_group,
)
from app.core.queue import streams as streams_mod

logger = logging.getLogger(__name__)

# 强引用持有 after_commit 里 fire-and-forget 的发布任务，避免被 GC 提前回收。
_bg_tasks: set[asyncio.Task] = set()


async def publish_restock_requested(request_id: str) -> None:
    """建组（幂等）并 XADD 一条补货信号；Redis 故障由调用方 best-effort 兜。"""

    client = streams_mod._get_client()
    await ensure_group(client, RESTOCK_STREAM, RESTOCK_GROUP)
    await add_event(client, RESTOCK_STREAM, {"request_id": str(request_id)})


async def _publish_best_effort(request_id: str) -> None:
    try:
        await publish_restock_requested(request_id)
    except Exception:
        # DB requested 行已提交、DB 轮询兜底：广播失败只告警，绝不上抛污染 after_commit。
        logger.exception(
            "restock stream XADD failed for %s; DB poll remains the source of truth",
            request_id,
        )


def spawn_restock_notification(request_id: str) -> None:
    """在同步 after_commit 钩子里调度一次 best-effort XADD。

    门控关闭时直接返回、不接触 Redis；无运行中的事件循环（非 async 上下文）时
    只告警不抛。
    """

    if not get_settings().restock_stream_enabled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.exception("no running event loop; cannot enqueue restock signal")
        return
    task = loop.create_task(
        _publish_best_effort(request_id), name="loom-restock-notify"
    )
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
