"""Q128（段13/Q60）集成测试：客户效果回填 POST /api/effects/backfill。

口径（02 C1.72，接缝按推荐甲拍板）：
- 客户专用通道，无 Agent Key（与 Q122 客户写口同构：actor 在体、roles 恒空）；
- body {tenant_id, records[], actor}，source 服务端固定 customer-backfill
  （不接受客户端传入任意 source）；
- 每条 content_id 必须命中本租户非 discarded 成品，否则该条 422
  （index/field/message），整批 all-or-nothing——客户通道绝不产生孤儿；
- 幂等 (content_id,captured_at) 覆盖、新采集点追加、metrics 七键稀疏纪律
  与 Agent 通道完全一致（复用同一纯函数与持久化路径）；
- received_by=客户 actor id；审计 effect.customer_backfilled（tenant=客户租户）。

create_all 不跑迁移种子；成品由本文件 fixture 自插。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_DISCARDED, CONTENT_READY, ContentProduct
from app.core.db import Base, get_session
from app.core.effects.models import (
    CUSTOMER_BACKFILL_SOURCE,
    STATUS_MATCHED,
    STATUS_ORPHAN,
    EffectRecord,
)
from app.main import app

CUSTOMER = {"id": "cust-1", "roles": []}
TS1 = "2026-09-01T10:00:00Z"
TS2 = "2026-09-02T10:00:00Z"


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
        session.add_all([
            ContentProduct(
                content_id="c1", tenant_id="t1", product_space_id="ps-1",
                final_id="fcw-1", goal="种草", platform="douyin",
                status=CONTENT_READY,
            ),
            ContentProduct(
                content_id="c2", tenant_id="t1", product_space_id="ps-1",
                final_id="fcw-2", goal="种草", platform="douyin",
                status=CONTENT_DISCARDED,
            ),
            ContentProduct(
                content_id="c3", tenant_id="t2", product_space_id="ps-2",
                final_id="fcw-3", goal="种草", platform="douyin",
                status=CONTENT_READY,
            ),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _count(session_factory, **where) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(EffectRecord)
        if where:
            stmt = stmt.filter_by(**where)
        return (await session.execute(stmt)).scalar_one()


def _body(tenant_id, records, actor=CUSTOMER):
    return {"tenant_id": tenant_id, "records": records, "actor": actor}


# ---------- 主流程 / 无需 Agent Key ----------


async def test_happy_customer_backfill_no_agent_key(client, session_factory):
    ac = client
    r = await ac.post("/api/effects/backfill", json=_body("t1", [
        {"content_id": "c1", "platform_post_id": "https://x/1",
         "captured_at": TS1, "metrics": {"plays": 10, "read_rate": 0.4}},
    ]))
    assert r.status_code == 200, r.text
    assert r.json() == {"received": 1, "matched": 1, "orphan": 0, "upserted": 0}

    async with session_factory() as session:
        row = (await session.scalars(
            select(EffectRecord).where(EffectRecord.external_content_id == "c1")
        )).one()
        assert row.source == CUSTOMER_BACKFILL_SOURCE
        assert row.status == STATUS_MATCHED
        assert row.matched_content_id == "c1"
        assert row.tenant_id == "t1"
        assert row.received_by == "cust-1"
        assert row.metrics == {"plays": 10, "read_rate": 0.4}


async def test_backfill_idempotent_overwrite_and_series_append(
    client, session_factory
):
    ac = client
    payload = _body("t1", [
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1,
         "metrics": {"plays": 1}},
    ])
    assert (await ac.post("/api/effects/backfill", json=payload)).json()["upserted"] == 0
    # 同采集点重推 → 覆盖。
    payload["records"][0]["metrics"] = {"plays": 8}
    r = await ac.post("/api/effects/backfill", json=payload)
    assert r.json() == {"received": 1, "matched": 1, "orphan": 0, "upserted": 1}
    assert await _count(session_factory, external_content_id="c1") == 1
    # 新采集点 → 追加。
    payload["records"][0]["captured_at"] = TS2
    r = await ac.post("/api/effects/backfill", json=payload)
    assert r.json()["upserted"] == 0
    assert await _count(session_factory, external_content_id="c1") == 2


# ---------- 租户隔离 / 孤儿禁产 ----------


async def test_backfill_other_tenant_content_422(client, session_factory):
    ac = client
    # c1 属 t1，用 t2 身份回填 → 拒，不落库。
    r = await ac.post("/api/effects/backfill", json=_body("t2", [
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1},
    ]))
    assert r.status_code == 422
    assert r.json()["detail"]["field"] == "content_id"
    assert r.json()["detail"]["index"] == 0
    assert await _count(session_factory) == 0


async def test_backfill_unknown_and_discarded_content_422(client, session_factory):
    ac = client
    for bad_id in ("ghost", "c2"):  # 不存在 / 已作废
        r = await ac.post("/api/effects/backfill", json=_body("t1", [
            {"content_id": bad_id, "platform_post_id": "p", "captured_at": TS1},
        ]))
        assert r.status_code == 422, r.text
        assert await _count(session_factory) == 0
    assert await _count(session_factory, status=STATUS_ORPHAN) == 0


async def test_backfill_whole_batch_rejected_on_one_bad_row(client, session_factory):
    ac = client
    r = await ac.post("/api/effects/backfill", json=_body("t1", [
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS2},
        {"content_id": "c3", "platform_post_id": "p", "captured_at": TS1},  # 他租户
    ]))
    assert r.status_code == 422
    assert r.json()["detail"]["index"] == 1
    assert await _count(session_factory) == 0


# ---------- 校验纪律与 Agent 通道一致 ----------


async def test_backfill_metrics_and_ts_validation_all_or_nothing(
    client, session_factory
):
    ac = client
    bad_records = [
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1,
         "metrics": {"followers": 1}},      # 未知键
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1,
         "metrics": {"plays": -1}},         # 负计数
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1,
         "metrics": {"read_rate": 2}},      # 越界比率
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1,
         "metrics": {"plays": True}},       # bool
        {"content_id": "c1", "platform_post_id": "p",
         "captured_at": "2026-09-01T10:00:00"},  # naive 时间
    ]
    for rec in bad_records:
        r = await ac.post("/api/effects/backfill", json=_body("t1", [rec]))
        assert r.status_code == 422, r.text
        assert await _count(session_factory) == 0


async def test_backfill_empty_tenant_and_records_422(client):
    ac = client
    assert (await ac.post("/api/effects/backfill", json=_body("t1", []))).status_code == 422
    assert (await ac.post("/api/effects/backfill", json={
        "tenant_id": "", "records": [
            {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1}],
        "actor": CUSTOMER,
    })).status_code == 422


async def test_backfill_duplicate_point_within_batch_422(client, session_factory):
    ac = client
    r = await ac.post("/api/effects/backfill", json=_body("t1", [
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1},
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1},
    ]))
    assert r.status_code == 422
    assert await _count(session_factory) == 0
