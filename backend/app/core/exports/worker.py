"""Q137 导出任务真后台 worker（Redis Streams 消费组，水平并行/崩溃接管/死信）。

与 Q87 restock worker 的区别：导出是**只读、幂等**渲染（下载按任务参数重查，
不存 payload），故不走 leader 单实例锁，而是用 Q134 消费组语义支持多副本各消费
一部分任务：

- ``XREADGROUP >`` 读新任务即入 PEL，处理完成才 ``XACK``；
- 崩溃在 ACK 前的任务留在 PEL，``XPENDING``+``XCLAIM`` 由任一副本在空闲阈值后
  接管重试（投递计数 +1）；
- 累计投递超 ``MAX_DELIVERIES`` 的任务进死信流并置 failed，避免无限重投；
- 处理中异常且未超限时不 ACK（留 PEL 等待接管）；任务已终态的重复投递直接 ACK
  丢弃（幂等）；任务尚不可见（请求未提交）同样留 PEL 下轮再接。

门控 ``LOOM_EXPORT_WORKER_ENABLED`` 默认 false：关闭时 POST /jobs 维持 Q132
请求内同步 completed 形态，不启动本循环、不接触 Redis。无 PG 迁移（status 为
String(16)，queued/running 直接写入）。
"""

import asyncio
import contextlib
import logging
import uuid

from app.core.exports import service
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
)
from app.core.queue import streams as streams_mod

logger = logging.getLogger(__name__)

# Redis 故障 tick 后的退避节拍（秒），避免无阻塞地忙轮询。
BACKEND_RETRY_SECONDS = 5.0


class ExportWorker:
    """进程内导出任务消费循环，形态与 RestockWorker/SweepScheduler 同构。"""

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
        self._consumer = consumer_name or f"export-{uuid.uuid4().hex[:8]}"
        self._block_ms = block_ms
        self._count = count
        self._min_idle_ms = min_idle_ms
        self._max_deliveries = max_deliveries
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # 可观测/测试：完成/失败/接管计数。
        self.completed = 0
        self.failed = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        logger.info("export worker starting consumer=%s", self._consumer)
        self._task = asyncio.create_task(self._loop(), name="loom-export-worker")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except StreamBackendError:
                # Redis 故障 fail-closed：消息在 PEL 不丢，退避后下轮自愈。
                logger.exception("export worker tick skipped: stream backend unavailable")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=BACKEND_RETRY_SECONDS)
                except TimeoutError:
                    pass
            except Exception:
                logger.exception("export worker tick failed")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=BACKEND_RETRY_SECONDS)
                except TimeoutError:
                    pass

    async def _tick(self) -> None:
        client = streams_mod._get_client()
        await ensure_group(client, service.EXPORT_STREAM, service.EXPORT_GROUP)
        new = await read_new(
            client,
            service.EXPORT_STREAM,
            service.EXPORT_GROUP,
            self._consumer,
            count=self._count,
            block_ms=self._block_ms,
        )
        for entry_id, fields in new:
            await self._handle(client, entry_id, fields, 1)
        # 崩溃接管：空闲超阈值的 PEL 行转由本消费者重试（投递计数 +1）。
        reclaimed = await reclaim_pending(
            client,
            service.EXPORT_STREAM,
            service.EXPORT_GROUP,
            self._consumer,
            min_idle_ms=self._min_idle_ms,
            count=self._count,
        )
        for entry_id, fields, deliveries in reclaimed:
            await self._handle(client, entry_id, fields, deliveries)

    async def _handle(
        self, client, entry_id: str, fields: dict[str, str], deliveries: int
    ) -> None:
        job_id = fields.get("job_id")
        async with self._factory() as session:
            job = await service.get_job(session, job_id) if job_id else None
            if job is None:
                # 请求未提交（消息早于 commit 可见）或非法消息：未超限留 PEL，
                # 由 reclaim 兜底；超限进死信后 ACK。
                if delivery_exhausted(deliveries, self._max_deliveries):
                    await self._dead_letter(client, entry_id, fields, "job-not-found")
                else:
                    logger.warning("export job %s not visible yet; leave in PEL", job_id)
                return
            if service.is_terminal(job):
                # 重复投递（崩溃前已完成）：幂等 ACK，不重复渲染。
                await ack_event(
                    client, service.EXPORT_STREAM, service.EXPORT_GROUP, entry_id
                )
                return
            try:
                await service.process_export_job(session, job)
                await session.commit()
            except Exception as exc:  # 渲染/DB 故障：未超限留 PEL 重试，超限置 failed
                await session.rollback()
                logger.exception("export job %s attempt %s failed", job_id, deliveries)
                if delivery_exhausted(deliveries, self._max_deliveries):
                    async with self._factory() as fail_session:
                        fresh = await service.get_job(fail_session, job_id)
                        if fresh is not None and not service.is_terminal(fresh):
                            await service.fail_export_job(
                                fail_session, fresh, f"{type(exc).__name__}: {exc}"
                            )
                            await fail_session.commit()
                    await self._dead_letter(
                        client, entry_id, fields, "max-deliveries-exceeded"
                    )
                return
        # 提交成功后再 ACK（ACK 失败则靠 reclaim 幂等重处理，终态判断会丢弃）。
        await ack_event(client, service.EXPORT_STREAM, service.EXPORT_GROUP, entry_id)
        self.completed += 1
        logger.info(
            "export consumer=%s completed job %s after %s delivery(ies)",
            self._consumer, job_id, deliveries,
        )

    async def _dead_letter(
        self, client, entry_id: str, fields: dict[str, str], reason: str
    ) -> None:
        await move_to_dead(
            client,
            service.EXPORT_STREAM,
            service.EXPORT_GROUP,
            service.EXPORT_DEAD_STREAM,
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


def build_export_workers(
    session_factory,
    *,
    concurrency: int = 1,
    block_ms: int = 5_000,
    count: int = DEFAULT_COUNT,
    min_idle_ms: int = DEFAULT_MIN_IDLE_MS,
    max_deliveries: int = DEFAULT_MAX_DELIVERIES,
) -> list[ExportWorker]:
    """Q152：按并发度构造同一消费组内的 N 个 consumer（单进程多 consumer 分片）。

    消费组语义保证每个 consumer 以 ``XREADGROUP >`` 各取不重叠的新消息，故 N>1
    即在单进程内水平扩展导出处理能力（崩溃接管仍按 consumer 各自的 PEL 进行）；
    默认 concurrency=1 与 V1 单 worker 完全一致。N>1 时姊妹 consumer 共享同一
    随机前缀并带序号后缀，便于 PEL/日志按 consumer 溯源。非法并发度/批量在启动
    期 fail-loud，不静默退化。
    """
    if concurrency < 1:
        raise ValueError("export worker concurrency must be >= 1")
    if count < 1:
        raise ValueError("export stream count must be >= 1")
    suffix = uuid.uuid4().hex[:8]
    workers: list[ExportWorker] = []
    for index in range(concurrency):
        # concurrency=1 时传 None 沿用构造器默认命名 export-{hex8}（既有行为）。
        name = None if concurrency == 1 else f"export-{suffix}-{index + 1}"
        workers.append(
            ExportWorker(
                session_factory,
                consumer_name=name,
                block_ms=block_ms,
                count=count,
                min_idle_ms=min_idle_ms,
                max_deliveries=max_deliveries,
            )
        )
    return workers
