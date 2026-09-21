"""Q161 客户效果批量回填导入 worker（Redis Streams 消费组，镜像 Q137 ExportWorker）。

导入是写、payload 已落 import_jobs 表可重放，Q128 幂等覆盖（content+captured_at）
使重复投递不会产生重复数据，故与导出一样无需 leader 单实例锁，消费组支持多副本
各消费一部分任务：

- ``XREADGROUP >`` 读新任务即入 PEL，处理完成才 ``XACK``；
- 崩溃在 ACK 前的任务留 PEL，``XCLAIM`` 在空闲阈值后由任一副本接管重试；
- 累计投递超 ``MAX_DELIVERIES`` 进死信流并置 failed；
- 确定性业务校验失败已在 service.process_import_job 内置 failed，这里照常提交并
  ACK（计 failed、不重试、不进死信）；只有基础设施异常才留 PEL 接管；
- 任务已终态的重复投递直接 ACK 丢弃（幂等）；任务尚不可见同样留 PEL 下轮再接。

门控 ``LOOM_IMPORT_WORKER_ENABLED`` 默认 false：关闭时 POST /jobs 请求内同步跑到
终态，不启动本循环、不接触 Redis。
"""

import asyncio
import contextlib
import logging
import uuid

from app.core.imports import service
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

BACKEND_RETRY_SECONDS = 5.0


class ImportWorker:
    """进程内导入任务消费循环，形态与 ExportWorker/RestockWorker 同构。"""

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
        self._consumer = consumer_name or f"import-{uuid.uuid4().hex[:8]}"
        self._block_ms = block_ms
        self._count = count
        self._min_idle_ms = min_idle_ms
        self._max_deliveries = max_deliveries
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # 可观测/测试：消息消费完成数 / 终态 failed 数。
        self.completed = 0
        self.failed = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        logger.info("import worker starting consumer=%s", self._consumer)
        self._task = asyncio.create_task(self._loop(), name="loom-import-worker")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except StreamBackendError:
                logger.exception("import worker tick skipped: stream backend unavailable")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=BACKEND_RETRY_SECONDS)
                except TimeoutError:
                    pass
            except Exception:
                logger.exception("import worker tick failed")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=BACKEND_RETRY_SECONDS)
                except TimeoutError:
                    pass

    async def _tick(self) -> None:
        client = streams_mod._get_client()
        await ensure_group(client, service.IMPORT_STREAM, service.IMPORT_GROUP)
        new = await read_new(
            client,
            service.IMPORT_STREAM,
            service.IMPORT_GROUP,
            self._consumer,
            count=self._count,
            block_ms=self._block_ms,
        )
        for entry_id, fields in new:
            await self._handle(client, entry_id, fields, 1)
        reclaimed = await reclaim_pending(
            client,
            service.IMPORT_STREAM,
            service.IMPORT_GROUP,
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
                if delivery_exhausted(deliveries, self._max_deliveries):
                    await self._dead_letter(client, entry_id, fields, "job-not-found")
                else:
                    logger.warning("import job %s not visible yet; leave in PEL", job_id)
                return
            if service.is_terminal(job):
                # 重复投递（崩溃前已终态）：幂等 ACK，不重复执行写操作。
                await ack_event(
                    client, service.IMPORT_STREAM, service.IMPORT_GROUP, entry_id
                )
                return
            try:
                job = await service.process_import_job(session, job)
                await session.commit()
            except Exception as exc:
                # 仅基础设施异常到这里（确定性业务失败已在 process 内置 failed）。
                await session.rollback()
                logger.exception("import job %s attempt %s failed", job_id, deliveries)
                if delivery_exhausted(deliveries, self._max_deliveries):
                    async with self._factory() as fail_session:
                        fresh = await service.get_job(fail_session, job_id)
                        if fresh is not None and not service.is_terminal(fresh):
                            await service.fail_import_job(
                                fail_session,
                                fresh,
                                f"max deliveries ({self._max_deliveries}) exceeded: {exc}",
                            )
                            await fail_session.commit()
                    await self._dead_letter(
                        client, entry_id, fields, "max-deliveries-exceeded"
                    )
                return
            terminal_failed = job.status == "failed"
        # 提交成功后再 ACK（ACK 失败靠 reclaim 幂等重处理，终态判断会丢弃）。
        await ack_event(client, service.IMPORT_STREAM, service.IMPORT_GROUP, entry_id)
        if terminal_failed:
            # 确定性业务失败：任务终态 failed，但消息已被正常消费（不重试）。
            self.failed += 1
        else:
            self.completed += 1
        logger.info(
            "import consumer=%s processed job %s after %s delivery(ies), status=%s",
            self._consumer, job_id, deliveries,
            "failed" if terminal_failed else "completed",
        )

    async def _dead_letter(
        self, client, entry_id: str, fields: dict[str, str], reason: str
    ) -> None:
        await move_to_dead(
            client,
            service.IMPORT_STREAM,
            service.IMPORT_GROUP,
            service.IMPORT_DEAD_STREAM,
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


def build_import_workers(
    session_factory,
    *,
    concurrency: int = 1,
    block_ms: int = 5_000,
    count: int = DEFAULT_COUNT,
    min_idle_ms: int = DEFAULT_MIN_IDLE_MS,
    max_deliveries: int = DEFAULT_MAX_DELIVERIES,
) -> list[ImportWorker]:
    """按并发度构造同一消费组内的 N 个 consumer（镜像 Q152 导出多 consumer）。

    消费组语义保证每个 consumer 以 XREADGROUP ">" 各取不重叠新消息，N>1 即水平
    扩展导入处理能力；默认 concurrency=1 与 V1 单 worker 完全一致。
    """

    if concurrency < 1:
        raise ValueError("import worker concurrency must be >= 1")
    if count < 1:
        raise ValueError("import stream count must be >= 1")
    suffix = uuid.uuid4().hex[:8]
    workers: list[ImportWorker] = []
    for index in range(concurrency):
        name = None if concurrency == 1 else f"import-{suffix}-{index + 1}"
        workers.append(
            ImportWorker(
                session_factory,
                consumer_name=name,
                block_ms=block_ms,
                count=count,
                min_idle_ms=min_idle_ms,
                max_deliveries=max_deliveries,
            )
        )
    return workers
