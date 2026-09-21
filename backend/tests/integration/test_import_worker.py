"""Q161 导入后台 worker 集成测试（内存 SQLite + FakeStreamsRedis，无真 Redis）。

镜像 Q137 导出 worker 测试，重点覆盖导入写侧的差异：确定性业务校验失败
（CsvValidationError / EffectValidationError）在 process_import_job 内置 failed，
worker 照常提交并 ACK（不进 PEL 重试、不进死信）；只有基础设施异常才留 PEL 由
XCLAIM 接管、超 MAX_DELIVERIES 进死信并置 failed。
"""

import base64
import io

import pytest_asyncio
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_READY, ContentProduct
from app.core.db import Base
from app.core.effects.models import EffectRecord
from app.core.imports import service
from app.core.imports.models import (
    JOB_COMPLETED,
    JOB_FAILED,
)
from app.core.imports.schemas import BackfillImportJobIn
from app.core.imports.worker import ImportWorker
from app.core.queue import (
    add_event,
    ensure_group,
    override_stream_client,
    read_new,
)
from app.core.queue import streams as streams_mod
from tests.integration.stream_fakes import FakeStreamsRedis

CUSTOMER = {"id": "cust-1", "roles": []}

HEADER = [
    "platform_post_id", "captured_at", "plays", "likes", "comments", "shares",
    "inquiries", "conversions", "read_rate",
]

CSV_TWO_ROWS = (
    ",".join(HEADER) + "\n"
    "p1,2026-09-01T10:00:00Z,100,10,1,0,0,0,0.5\n"
    "p2,2026-09-01T12:00:00+08:00,200,,,,,,\n"
)
CSV_BAD_ROW = (
    ",".join(HEADER) + "\n"
    "p1,2026-09-01T10:00:00Z,-1,,,,,,\n"  # 负计数：确定性逐行错误（恰 9 列）
)


def _xlsx_b64(rows) -> str:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


@pytest_asyncio.fixture
def fake():
    redis_client = FakeStreamsRedis()
    override_stream_client(redis_client)
    yield redis_client
    override_stream_client(None)


async def _seed_content(factory) -> None:
    async with factory() as session:
        session.add(
            ContentProduct(
                content_id="c1", tenant_id="t1", product_space_id="ps-1",
                final_id="fcw-1", goal="种草", platform="douyin",
                status=CONTENT_READY,
            )
        )
        await session.commit()


def _csv_body(csv_text: str) -> BackfillImportJobIn:
    return BackfillImportJobIn(
        tenant_id="t1", content_id="c1", format="csv",
        csv=csv_text, filename="b.csv", actor=CUSTOMER,
    )


async def _queued_job(factory, body) -> str:
    async with factory() as session:
        job = await service.create_queued_import_job(session, body)
        await session.commit()
        return job.job_id


def _pel(fake) -> dict:
    return fake.groups[(service.IMPORT_STREAM, service.IMPORT_GROUP)]["pel"]


async def test_completes_new_csv_job_and_acks(factory, fake):
    await _seed_content(factory)
    job_id = await _queued_job(factory, _csv_body(CSV_TWO_ROWS))
    await service.enqueue_import_job(job_id)

    worker = ImportWorker(factory, block_ms=0)
    await worker._tick()

    async with factory() as session:
        job = await service.get_job(session, job_id)
        assert job.status == JOB_COMPLETED
        assert job.received == 2
        assert job.matched == 2
        assert job.orphan == 0
        assert job.row_count == 2
        assert job.completed_at is not None
        assert job.errors is None
        # 回填确已落库（两行）。
        records = list(
            (await session.scalars(select(EffectRecord))).all()
        )
    assert len(records) == 2
    assert worker.completed == 1
    assert _pel(fake) == {}  # 成功即 ACK，PEL 清空


async def test_completes_xlsx_job(factory, fake):
    await _seed_content(factory)
    body = BackfillImportJobIn(
        tenant_id="t1", content_id="c1", format="xlsx",
        content_base64=_xlsx_b64([HEADER, ["p1", "2026-09-01T10:00:00Z", 100]]),
        filename="b.xlsx", actor=CUSTOMER,
    )
    job_id = await _queued_job(factory, body)
    await service.enqueue_import_job(job_id)

    worker = ImportWorker(factory, block_ms=0)
    await worker._tick()

    async with factory() as session:
        job = await service.get_job(session, job_id)
        assert job.status == JOB_COMPLETED
        assert job.matched == 1
    assert worker.completed == 1
    assert _pel(fake) == {}


async def test_validation_failure_marks_failed_and_acks_without_retry(factory, fake):
    # 关键差异：确定性业务失败置 failed 并 ACK，不进 PEL 重试、不进死信、不入库。
    await _seed_content(factory)
    job_id = await _queued_job(factory, _csv_body(CSV_BAD_ROW))
    await service.enqueue_import_job(job_id)

    worker = ImportWorker(factory, block_ms=0)
    await worker._tick()

    async with factory() as session:
        job = await service.get_job(session, job_id)
        assert job.status == JOB_FAILED
        assert job.error
        import json as _json

        errors = _json.loads(job.errors)
        assert isinstance(errors, list) and errors
        records = list((await session.scalars(select(EffectRecord))).all())
    assert records == []  # all-or-nothing：坏批零落库
    assert worker.failed == 1
    assert worker.completed == 0
    assert _pel(fake) == {}  # 已 ACK，不留 PEL
    assert service.IMPORT_DEAD_STREAM not in fake.streams  # 不进死信


async def test_reclaims_crashed_pending_and_completes(factory, fake):
    await _seed_content(factory)
    job_id = await _queued_job(factory, _csv_body(CSV_TWO_ROWS))
    await service.enqueue_import_job(job_id)

    # 另一消费者读走即“崩溃”（不 ACK），消息留在 PEL。
    client = streams_mod._get_client()
    await read_new(
        client, service.IMPORT_STREAM, service.IMPORT_GROUP, "crashed", count=10
    )
    assert len(_pel(fake)) == 1

    worker = ImportWorker(factory, block_ms=0, min_idle_ms=0)
    await worker._tick()
    async with factory() as session:
        job = await service.get_job(session, job_id)
        assert job.status == JOB_COMPLETED
        assert job.matched == 2
    assert _pel(fake) == {}


async def test_terminal_duplicate_is_acked_without_reprocessing(
    factory, fake, monkeypatch
):
    await _seed_content(factory)
    job_id = await _queued_job(factory, _csv_body(CSV_TWO_ROWS))
    async with factory() as session:
        job = await service.get_job(session, job_id)
        job = await service.process_import_job(session, job)
        await session.commit()

    await service.enqueue_import_job(job_id)
    called = {"n": 0}

    async def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("must not reprocess a terminal job")

    monkeypatch.setattr(service, "process_import_job", _boom)
    worker = ImportWorker(factory, block_ms=0)
    await worker._tick()
    assert called["n"] == 0
    assert _pel(fake) == {}


async def test_invisible_job_left_in_pel_when_under_limit(factory, fake):
    client = streams_mod._get_client()
    await ensure_group(client, service.IMPORT_STREAM, service.IMPORT_GROUP)
    await add_event(client, service.IMPORT_STREAM, {"job_id": "ghost"})

    worker = ImportWorker(factory, block_ms=0, max_deliveries=5)
    await worker._tick()
    assert worker.failed == 0
    assert len(_pel(fake)) == 1  # 未 ACK，等 reclaim


async def test_invisible_job_dead_lettered_after_limit(factory, fake):
    client = streams_mod._get_client()
    await ensure_group(client, service.IMPORT_STREAM, service.IMPORT_GROUP)
    await add_event(client, service.IMPORT_STREAM, {"job_id": "ghost"})
    await read_new(
        client, service.IMPORT_STREAM, service.IMPORT_GROUP, "crashed", count=10
    )

    worker = ImportWorker(factory, block_ms=0, min_idle_ms=0, max_deliveries=1)
    await worker._tick()  # reclaim deliveries=2 > max 1 → 死信
    assert worker.failed == 1
    assert _pel(fake) == {}
    dead = fake.streams[service.IMPORT_DEAD_STREAM]
    assert len(dead) == 1
    assert dead[0][1]["job_id"] == "ghost"


async def test_infra_failure_under_limit_stays_in_pel(factory, fake, monkeypatch):
    await _seed_content(factory)
    job_id = await _queued_job(factory, _csv_body(CSV_TWO_ROWS))
    await service.enqueue_import_job(job_id)

    async def _boom(*_a, **_k):
        raise RuntimeError("database down")

    monkeypatch.setattr(service, "process_import_job", _boom)
    worker = ImportWorker(factory, block_ms=0)
    await worker._tick()  # delivery=1 未超限：留 PEL
    assert len(_pel(fake)) == 1
    async with factory() as session:
        job = await service.get_job(session, job_id)
        assert job.status != JOB_FAILED  # 未到死信阈值，不置 failed


async def test_infra_failure_over_limit_dead_letters_and_fails_job(
    factory, fake, monkeypatch
):
    await _seed_content(factory)
    job_id = await _queued_job(factory, _csv_body(CSV_TWO_ROWS))
    await service.enqueue_import_job(job_id)

    # 先让一条消息进 PEL（模拟崩溃投递历史）。
    client = streams_mod._get_client()
    await read_new(
        client, service.IMPORT_STREAM, service.IMPORT_GROUP, "crashed", count=10
    )

    async def _boom(*_a, **_k):
        raise RuntimeError("database down")

    monkeypatch.setattr(service, "process_import_job", _boom)
    worker = ImportWorker(factory, block_ms=0, min_idle_ms=0, max_deliveries=1)
    await worker._tick()  # reclaim deliveries=2 > max 1 → 死信 + failed
    assert _pel(fake) == {}
    assert service.IMPORT_DEAD_STREAM in fake.streams
    async with factory() as session:
        job = await service.get_job(session, job_id)
        assert job.status == JOB_FAILED
        assert "database down" in (job.error or "")
