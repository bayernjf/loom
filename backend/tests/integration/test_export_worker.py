"""Q137 导出后台 worker 集成测试（内存 SQLite + FakeStreamsRedis，无真 Redis）。

覆盖：新消息置 completed 并 ACK、崩溃 PEL 行 XCLAIM 接管重试、超限行进死信并
置 failed、终态任务重复投递幂等 ACK、任务尚不可见留 PEL、处理异常未超限留 PEL、
Redis 故障 fail-closed。
"""


import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.exports import service
from app.core.exports.models import (
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_QUEUED,
)
from app.core.exports.worker import ExportWorker
from app.core.queue import (
    StreamBackendError,
    add_event,
    ensure_group,
    override_stream_client,
    read_new,
)
from app.core.queue import streams as streams_mod
from app.core.tenants.models import Tenant
from app.final.final_whitelist.models import FinalContentWhitelist
from tests.integration.stream_fakes import FakeStreamsRedis


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


def _fcw(seq: int) -> FinalContentWhitelist:
    return FinalContentWhitelist(
        tenant_id="t1",
        product_space_id="ps-1",
        pws_id=f"pws-{seq}",
        pwc_id=f"pwc-{seq}",
        pcp_id="pcp-1",
        csp_package_id="csp-1",
        cstp_package_id="cstp-1",
        cep_package_id="cep-1",
        platform="xhs",
        slot_id=f"slot-{seq}",
        goal="ENGAGEMENT",
        guards_passed=True,
        publish_status="published",
        issued_by="ops-1",
    )


async def _seed(factory, *, fcw: int = 1) -> None:
    async with factory() as session:
        session.add(Tenant(tenant_id="t1", name="试点", plan="basic", status="active"))
        session.add_all([_fcw(i) for i in range(fcw)])
        await session.commit()


async def _queued_job(factory, *, fmt: str = "csv") -> str:
    async with factory() as session:
        job = await service.create_queued_export_job(
            session,
            tenant_id="t1",
            product_space_id=None,
            fmt=fmt,
            actor_id="mg-1",
        )
        await session.commit()
        return job.job_id


def _pel(fake) -> dict:
    return fake.groups[(service.EXPORT_STREAM, service.EXPORT_GROUP)]["pel"]


async def test_completes_new_job_and_acks(factory, fake):
    await _seed(factory, fcw=2)
    job_id = await _queued_job(factory)
    await service.enqueue_export_job(job_id)

    worker = ExportWorker(factory, block_ms=0)
    await worker._tick()

    async with factory() as session:
        job = await service.get_job(session, job_id)
        assert job.status == JOB_COMPLETED
        assert job.row_count == 2
        assert job.completed_at is not None
    assert worker.completed == 1
    assert _pel(fake) == {}  # 成功即 ACK，PEL 清空


async def test_reclaims_crashed_pending_and_completes(factory, fake):
    await _seed(factory, fcw=1)
    job_id = await _queued_job(factory)
    await service.enqueue_export_job(job_id)

    # 另一消费者读走即“崩溃”（不 ACK），消息留在 PEL。
    client = streams_mod._get_client()
    await read_new(
        client, service.EXPORT_STREAM, service.EXPORT_GROUP, "crashed", count=10
    )
    pel_fields = [v["fields"] for v in _pel(fake).values()]
    assert any(f["job_id"] == job_id for f in pel_fields)

    # 新 worker 空闲阈值 0 接管（deliveries=2）并完成。
    worker = ExportWorker(factory, block_ms=0, min_idle_ms=0)
    await worker._tick()
    async with factory() as session:
        job = await service.get_job(session, job_id)
        assert job.status == JOB_COMPLETED
        assert job.row_count == 1
    assert _pel(fake) == {}


async def test_terminal_duplicate_is_acked_without_reprocessing(factory, fake, monkeypatch):
    await _seed(factory)
    job_id = await _queued_job(factory)
    async with factory() as session:
        job = await service.get_job(session, job_id)
        await service.process_export_job(session, job)
        await session.commit()

    await service.enqueue_export_job(job_id)
    called = {"n": 0}

    async def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("must not reprocess a terminal job")

    monkeypatch.setattr(service, "process_export_job", _boom)
    worker = ExportWorker(factory, block_ms=0)
    await worker._tick()
    assert called["n"] == 0
    assert worker.completed == 0
    assert _pel(fake) == {}  # 重复投递直接 ACK 丢弃


async def test_invisible_job_left_in_pel_when_under_limit(factory, fake):
    # 组存在但消息指向尚不可见/不存在的 job：未超限留 PEL 等 reclaim。
    client = streams_mod._get_client()
    await ensure_group(client, service.EXPORT_STREAM, service.EXPORT_GROUP)
    await add_event(client, service.EXPORT_STREAM, {"job_id": "ghost"})

    worker = ExportWorker(factory, block_ms=0, max_deliveries=5)
    await worker._tick()
    assert worker.failed == 0
    assert len(_pel(fake)) == 1  # 未 ACK


async def test_invisible_job_dead_lettered_after_limit(factory, fake):
    client = streams_mod._get_client()
    await ensure_group(client, service.EXPORT_STREAM, service.EXPORT_GROUP)
    await add_event(client, service.EXPORT_STREAM, {"job_id": "ghost"})
    # 模拟崩溃投递历史：读走入 PEL。
    await read_new(
        client, service.EXPORT_STREAM, service.EXPORT_GROUP, "crashed", count=10
    )

    worker = ExportWorker(factory, block_ms=0, min_idle_ms=0, max_deliveries=1)
    await worker._tick()  # reclaim deliveries=2 > max 1 → 死信
    assert worker.failed == 1
    assert _pel(fake) == {}
    dead = fake.streams[service.EXPORT_DEAD_STREAM]
    assert len(dead) == 1
    assert dead[0][1]["_dead_reason"] == "job-not-found"
    assert dead[0][1]["job_id"] == "ghost"


async def test_repeated_processing_failure_fails_job_and_dead_letters(
    factory, fake, monkeypatch
):
    await _seed(factory)
    job_id = await _queued_job(factory)
    await service.enqueue_export_job(job_id)

    async def _boom(*_a, **_k):
        raise RuntimeError("render backend down")

    monkeypatch.setattr(service, "process_export_job", _boom)
    # 首轮：默认 60s 空闲阈值，新消息 delivery=1 失败后留 PEL，不会同轮立即 reclaim。
    first = ExportWorker(factory, block_ms=0, max_deliveries=1)
    await first._tick()
    async with factory() as session:
        assert (await service.get_job(session, job_id)).status == JOB_QUEUED
    assert len(_pel(fake)) == 1

    # 60s 后另一 worker 接管（min_idle=0），delivery=2 > max 1：置 failed + 死信。
    second = ExportWorker(factory, block_ms=0, min_idle_ms=0, max_deliveries=1)
    await second._tick()
    async with factory() as session:
        job = await service.get_job(session, job_id)
        assert job.status == JOB_FAILED
        assert "render backend down" in (job.error or "")
    assert second.failed == 1
    assert _pel(fake) == {}
    assert service.EXPORT_DEAD_STREAM in fake.streams


async def test_stream_backend_failure_is_fail_closed(factory, fake):
    failing = FakeStreamsRedis(fail=True)
    override_stream_client(failing)
    worker = ExportWorker(factory, block_ms=0)
    with pytest.raises(StreamBackendError):
        await worker._tick()
