"""Q138 restock requested 信号 XADD 生产接线集成测试（内存 SQLite + FakeStreamsRedis）。

口径（02 C1.82，推荐甲案）：只接生产侧——requested 行提交后 best-effort XADD 到
restock 流；DB 行是事实源，XADD 失败不影响落库；门控关闭不接触 Redis；消费组水平
并行消费留 V2（Q87/Q89 花钱单实例裁决）。
"""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db import Base
from app.core.queue import RESTOCK_GROUP, RESTOCK_STREAM, override_stream_client
from app.core.restock import notify as notify_mod
from app.core.skill7 import service as skill7_service
from app.core.skill7.models import SkillRun
from tests.integration.stream_fakes import FakeStreamsRedis


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as open_session:
        yield open_session
    await engine.dispose()


async def _drain_bg_tasks() -> None:
    # after_commit 里 fire-and-forget 的 XADD 任务排空。
    tasks = list(notify_mod._bg_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _request_restock(session) -> str:
    run = await skill7_service.maybe_request_restock(
        session,
        tenant_id="t1",
        product_space_id="ps-1",
        ready_count=0,
        critical=10,
        cooldown_minutes=5,
    )
    assert run is not None
    await session.commit()
    return str(run.run_id)


async def test_requested_run_is_xadded_after_commit_when_enabled(
    session, monkeypatch: pytest.MonkeyPatch
):
    fake = FakeStreamsRedis()
    override_stream_client(fake)
    monkeypatch.setattr(get_settings(), "restock_stream_enabled", True)
    try:
        request_id = await _request_restock(session)
        await _drain_bg_tasks()
    finally:
        override_stream_client(None)

    assert (RESTOCK_STREAM, RESTOCK_GROUP) in fake.groups  # 幂等建组
    entries = fake.streams[RESTOCK_STREAM]
    assert len(entries) == 1
    assert entries[0][1]["request_id"] == request_id


async def test_no_redis_touch_when_disabled(session, monkeypatch: pytest.MonkeyPatch):
    fake = FakeStreamsRedis()
    override_stream_client(fake)
    monkeypatch.setattr(get_settings(), "restock_stream_enabled", False)
    try:
        await _request_restock(session)
        await _drain_bg_tasks()
    finally:
        override_stream_client(None)

    # 门控关闭：不建组、不入流，但 requested 行照常落库。
    assert RESTOCK_STREAM not in fake.streams


async def test_xadd_failure_does_not_break_requested_run(
    session, monkeypatch: pytest.MonkeyPatch
):
    failing = FakeStreamsRedis(fail=True)
    override_stream_client(failing)
    monkeypatch.setattr(get_settings(), "restock_stream_enabled", True)
    try:
        request_id = await _request_restock(session)  # 不抛
        await _drain_bg_tasks()  # best-effort 吞掉 XADD 故障
    finally:
        override_stream_client(None)

    # DB requested 行仍是事实源，不受 XADD 失败影响。
    run = await session.get(SkillRun, request_id)
    assert run is not None
    assert run.status == "requested"
    assert run.source == "restock_auto"
