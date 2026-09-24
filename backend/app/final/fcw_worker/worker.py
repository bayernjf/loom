"""Q165 FCW 组装后台 worker 实现（Redis Streams 消费组）。"""

import asyncio
import contextlib
import logging
import uuid

from app.core.queue import (
    DEFAULT_COUNT,
    DEFAULT_MAX_DELIVERIES,
    DEFAULT_MIN_IDLE_MS,
    StreamBackendError,
    ack_event,
    delivery_exhausted,
    ensure_group,
    move_to_dead,
    read_new,
    reclaim_pending,
    sample_stream_depth,
)
from app.core.queue import streams as streams_mod
from app.final.final_whitelist import service

logger = logging.getLogger(__name__)

BACKEND_RETRY_SECONDS = 5.0


class FcwWorker:
    """进程内 FCW 组装任务消费循环，形态与 ExportWorker/ImportWorker 同构。"""

    def __init__(
        self,
        session_factory,
        *,
        consumer_name: str | None = None,
        block_ms: int = 5_000,
        count: int = DEFAULT_COUNT,
        min_idle_ms: int = DEFAULT_MIN_IDLE_MS,
        max_deliveries: int = DEFAULT_MAX_DELIVERIES,
    ):
        self._factory = session_factory
        self._consumer = consumer_name or f"fcw-{uuid.uuid4().hex[:8]}"
        self._block_ms = block_ms
        self._count = count
        self._min_idle_ms = min_idle_ms
        self._max_deliveries = max_deliveries
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # 可观测/测试：任务完成数 / 死信 failed 数。
        self.completed = 0
        self.failed = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        logger.info("fcw worker starting consumer=%s", self._consumer)
        self._task = asyncio.create_task(self._loop(), name="loom-fcw-worker")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except StreamBackendError:
                logger.exception("fcw worker tick skipped: stream backend unavailable")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=BACKEND_RETRY_SECONDS)
                except TimeoutError:
                    pass
            except Exception:
                logger.exception("fcw worker tick failed")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=BACKEND_RETRY_SECONDS)
                except TimeoutError:
                    pass

    async def _tick(self) -> None:
        client = streams_mod._get_client()
        await ensure_group(client, service.FCW_STREAM, service.FCW_GROUP)
        new = await read_new(
            client,
            service.FCW_STREAM,
            service.FCW_GROUP,
            self._consumer,
            count=self._count,
            block_ms=self._block_ms,
        )
        for entry_id, fields in new:
            await self._handle(client, entry_id, fields, 1)
        reclaimed = await reclaim_pending(
            client,
            service.FCW_STREAM,
            service.FCW_GROUP,
            self._consumer,
            min_idle_ms=self._min_idle_ms,
            count=self._count,
        )
        for entry_id, fields, deliveries in reclaimed:
            await self._handle(client, entry_id, fields, deliveries)
        # Q188：每 tick 顺带取一次队列深度（纯观测读，故障不影响本轮）。
        await sample_stream_depth(client, service.FCW_STREAM, service.FCW_GROUP)

    async def _handle(
        self, client, entry_id: str, fields: dict[str, str], deliveries: int
    ) -> None:
        task_id = fields.get("task_id")
        async with self._factory() as session:
            task = await service.get_task(session, task_id) if task_id else None
            if task is None:
                # 幽灵 task_id（创建时已先提交再入流，正常路径任务必可见）：
                # 无重试价值，直接 ACK 丢弃（不崩溃）。
                await ack_event(
                    client, service.FCW_STREAM, service.FCW_GROUP, entry_id
                )
                return
            if service.is_terminal(task):
                # 重复投递（崩溃前已终态）：幂等 ACK，不重复组装。
                await ack_event(
                    client, service.FCW_STREAM, service.FCW_GROUP, entry_id
                )
                return
            try:
                task.status = service.TASK_STATUS_RUNNING
                await session.flush()
                actor = service._worker_actor(task.created_by)
                await service.process_task(session, task, actor)
                await session.commit()
            except Exception as exc:  # 基础设施异常：未超限留 PEL，超限置 failed
                await session.rollback()
                logger.exception(
                    "fcw task %s attempt %s failed", task_id, deliveries
                )
                if delivery_exhausted(deliveries, self._max_deliveries):
                    async with self._factory() as fail_session:
                        fresh = await service.get_task(fail_session, task_id)
                        if fresh is not None and not service.is_terminal(fresh):
                            await service.fail_fcw_task(
                                fail_session,
                                fresh,
                                f"max deliveries ({self._max_deliveries}) exceeded: {exc}",
                            )
                            await fail_session.commit()
                    await self._dead_letter(
                        client, entry_id, fields, "max-deliveries-exceeded"
                    )
                return
        # 提交成功后再 ACK（ACK 失败靠 reclaim 幂等重处理，终态判断会丢弃）。
        await ack_event(client, service.FCW_STREAM, service.FCW_GROUP, entry_id)
        self.completed += 1
        logger.info(
            "fcw consumer=%s completed task %s after %s delivery(ies)",
            self._consumer, task_id, deliveries,
        )

    async def _dead_letter(
        self, client, entry_id: str, fields: dict[str, str], reason: str
    ) -> None:
        await move_to_dead(
            client,
            service.FCW_STREAM,
            service.FCW_GROUP,
            service.FCW_DEAD_STREAM,
            entry_id,
            fields,
            reason=reason,
        )
        self.failed += 1

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


def build_fcw_workers(
    session_factory,
    *,
    concurrency: int = 1,
    block_ms: int = 5_000,
    count: int = DEFAULT_COUNT,
    min_idle_ms: int = DEFAULT_MIN_IDLE_MS,
    max_deliveries: int = DEFAULT_MAX_DELIVERIES,
) -> list[FcwWorker]:
    """按并发度构造同一消费组内的 N 个 consumer（镜像 Q152 导出多 consumer）。

    消费组语义保证每个 consumer 以 XREADGROUP ">" 各取不重叠新消息，N>1 即水平
    扩展组装处理能力；默认 concurrency=1 与 V1 单 worker 完全一致。非法并发度/批量
    在启动期 fail-loud，不静默退化。
    """
    if concurrency < 1:
        raise ValueError("fcw worker concurrency must be >= 1")
    if count < 1:
        raise ValueError("fcw stream count must be >= 1")
    suffix = uuid.uuid4().hex[:8]
    workers: list[FcwWorker] = []
    for index in range(concurrency):
        name = None if concurrency == 1 else f"fcw-{suffix}-{index + 1}"
        workers.append(
            FcwWorker(
                session_factory,
                consumer_name=name,
                block_ms=block_ms,
                count=count,
                min_idle_ms=min_idle_ms,
                max_deliveries=max_deliveries,
            )
        )
    return workers
