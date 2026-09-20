"""Q143 restock PG 行级 fencing 认领/提交前门原语测试（sqlite，C1.87）。

不经过模型网关：直接对 restock_claims 行验证 claim_request 的单调认领语义与
fence_current 的提交前条件更新门；fence=None（锁关闭）必须全程 no-op 放行。
worker 端到端（花钱前抢占/花钱中易主）见 test_restock_worker_api.py。
"""

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.restock.fencing import (
    CLAIM_ACQUIRED,
    CLAIM_HELD,
    CLAIM_LOST,
    claim_request,
    fence_current,
)
from app.core.restock.models import RestockClaim


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


async def test_claim_first_acquires_then_same_fence_held(factory):
    async with factory() as session:
        assert await claim_request(session, "req-1", 1, "owner-a") == CLAIM_ACQUIRED
        await session.commit()
    async with factory() as session:
        assert await claim_request(session, "req-1", 1, "owner-a") == CLAIM_HELD
        await session.commit()
    async with factory() as session:
        row = await session.get(RestockClaim, "req-1")
        assert row.fence == 1
        assert row.claimed_by == "owner-a"


async def test_larger_fence_takes_over_smaller_rejected(factory):
    async with factory() as session:
        await claim_request(session, "req-1", 1, "owner-a")
        await session.commit()
    # 新 leader（更大 fence）接管认领。
    async with factory() as session:
        assert await claim_request(session, "req-1", 2, "owner-b") == CLAIM_ACQUIRED
        await session.commit()
    # 旧 leader 的迟到认领被拒（lost）；新 leader 重入 held。
    async with factory() as session:
        assert await claim_request(session, "req-1", 1, "owner-a") == CLAIM_LOST
    async with factory() as session:
        assert await claim_request(session, "req-1", 2, "owner-b") == CLAIM_HELD
    async with factory() as session:
        row = await session.get(RestockClaim, "req-1")
        assert row.fence == 2
        assert row.claimed_by == "owner-b"


async def test_none_fence_is_noop_and_gate_always_open(factory):
    # fence=None（多副本锁关闭）：认领直接 held、不落行；门恒 True。
    async with factory() as session:
        assert await claim_request(session, "req-1", None) == CLAIM_HELD
        await session.commit()
        assert await fence_current(session, "req-1", None) is True
    async with factory() as session:
        rows = list((await session.scalars(select(RestockClaim))).all())
        assert rows == []


async def test_fence_current_gate_closes_after_takeover(factory):
    async with factory() as session:
        await claim_request(session, "req-1", 1, "owner-a")
        await session.commit()
    # 持锁者提交前门命中。
    async with factory() as session:
        assert await fence_current(session, "req-1", 1) is True
        await session.commit()
    # 花钱期间易主：新 leader 升到 fence=2。
    async with factory() as session:
        await claim_request(session, "req-1", 2, "owner-b")
        await session.commit()
    # 旧 leader 的条件更新命中 0 行 → 门关闭；新 leader 命中。
    async with factory() as session:
        assert await fence_current(session, "req-1", 1) is False
        await session.rollback()
    async with factory() as session:
        assert await fence_current(session, "req-1", 2) is True
        await session.commit()
