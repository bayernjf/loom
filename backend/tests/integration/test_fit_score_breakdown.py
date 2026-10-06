"""fit_score 可解释化集成测试（Q296 甲，design-v2-fit-score-selflearning §3.1）。

覆盖：breakdown 四行分项与聚合标量 Σ 自校验、权重与 GoalFitWeight 行一致、
incomplete 语义不动（fit_score=None 不凑分、分项 weight/contribution 为 None——
分可见、不造聚合）、既有响应键加法不破坏、纯只读零副作用（无审计行）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.main import app
from app.platform.platform_adaptation import pa_rules
from app.platform.platform_adaptation.models import GoalFitWeight, PublishSlot

PATH = "/api/admin/publish-slots/{slot_id}/fit-score"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                PublishSlot(
                    slot_id="slot-1",
                    platform="x_platform",
                    code="S-1",
                    name="测试发布位",
                    slot_type="short_video",
                    traffic=80,
                    safe=60,
                    conv=70,
                    load=50,
                ),
                GoalFitWeight(
                    goal="ENGAGEMENT",
                    weights={"traffic": 0.4, "safe": 0.2, "conv": 0.2, "load": 0.2},
                ),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_breakdown_sums_to_the_scalar(client):
    """矩阵齐：breakdown 四行与标量 Σ 逐位一致，权重与矩阵行同源。"""
    resp = await client.get(PATH.format(slot_id="slot-1"), params={"goal": "ENGAGEMENT"})
    assert resp.status_code == 200
    body = resp.json()
    # 既有键加法扩展，形状不破坏
    assert body["slot_id"] == "slot-1"
    assert body["goal"] == "ENGAGEMENT"
    assert body["incomplete"] is False
    assert body["fit_score"] == 80 * 0.4 + 60 * 0.2 + 70 * 0.2 + 50 * 0.2
    rows = body["breakdown"]
    assert [r["dim"] for r in rows] == list(pa_rules.FIT_DIMS)
    assert sum(r["contribution"] for r in rows) == body["fit_score"]
    by_dim = {r["dim"]: r for r in rows}
    assert by_dim["traffic"] == {"dim": "traffic", "score": 80, "weight": 0.4, "contribution": 32}
    assert by_dim["safe"]["weight"] == 0.2 and by_dim["safe"]["contribution"] == 12


async def test_incomplete_keeps_scores_visible_without_fabricated_weights(client):
    """目的未配矩阵：fit_score=None + incomplete，分项可见但 weight/contribution 为 None。"""
    resp = await client.get(PATH.format(slot_id="slot-1"), params={"goal": "NOPE"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fit_score"] is None
    assert body["incomplete"] is True
    assert [r["dim"] for r in body["breakdown"]] == list(pa_rules.FIT_DIMS)
    assert all(r["weight"] is None and r["contribution"] is None for r in body["breakdown"])
    assert {r["score"] for r in body["breakdown"]} == {80, 60, 70, 50}


async def test_unknown_slot_is_404(client):
    resp = await client.get(PATH.format(slot_id="nope"), params={"goal": "ENGAGEMENT"})
    assert resp.status_code == 404


async def test_preview_is_read_only_no_audit_rows(client, session_factory):
    """纯只读：请求前后审计行数不变（派生值不落库）。"""

    async def count_audit() -> int:
        async with session_factory() as session:
            return len((await session.scalars(select(AuditLog))).all())

    before = await count_audit()
    resp = await client.get(PATH.format(slot_id="slot-1"), params={"goal": "ENGAGEMENT"})
    assert resp.status_code == 200
    assert await count_audit() == before
