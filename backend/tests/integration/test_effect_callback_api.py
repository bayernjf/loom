"""Q126（段13/Q60）集成测试：POST /api/effect-callback + 运营只读队列。

口径（02 新 Q，接缝按推荐甲拍板）：
- 鉴权复用 Q88 一 Agent 一 Key（Bearer，缺失/错误/吊销统一 401）；
- 推送 content_id 命中有效成品→matched 并回填 tenant；对不上或命中
  discarded→orphan 孤儿队列；(content_id,captured_at) 幂等覆盖、新采集点追加；
- metrics 稀疏落库、缺席键不补 0；整批 all-or-nothing，任一非法 422 不写部分；
- 只读 GET orphans / 按 content 时序为 operations|platform_admin query 闸
  （缺 actor 422、客户 403）。人工认领（Q60a）/反哺校准随下一片，本片不涉。

create_all 不跑迁移种子；Agent Key 与成品由本文件 fixture 自插。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_DISCARDED, CONTENT_READY, ContentProduct
from app.core.actor import Actor
from app.core.api_keys.service import issue_key, revoke_key
from app.core.db import Base, get_session
from app.core.effects.models import STATUS_MATCHED, STATUS_ORPHAN, EffectRecord
from app.core.rbac import PLATFORM_ADMIN
from app.main import app

OPS_Q = {"actor_id": "ops-1", "roles": ["operations"]}
ADMIN_Q = {"actor_id": "admin-1", "roles": ["platform_admin"]}
CUSTOMER_Q = {"actor_id": "cust-1", "roles": []}

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
        active_row, active_plain = await issue_key(
            session, "agent-1", Actor(id="admin-1", roles=[PLATFORM_ADMIN])
        )
        dead_row, dead_plain = await issue_key(
            session, "agent-dead", Actor(id="admin-1", roles=[PLATFORM_ADMIN])
        )
        await revoke_key(session, dead_row.key_id, Actor(id="admin-1", roles=[PLATFORM_ADMIN]))
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
        ])
        await session.commit()
        secrets = {
            "active": active_plain,
            "dead": dead_plain,
            "active_key_id": active_row.key_id,
        }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, secrets


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


async def _count(session_factory, **where) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(EffectRecord)
        if where:
            stmt = stmt.filter_by(**where)
        return (await session.execute(stmt)).scalar_one()


# ---------- 鉴权 ----------


async def test_missing_bad_revoked_key_all_401(client):
    ac, keys = client
    payload = {"source": "agent-1", "records": [
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1},
    ]}
    assert (await ac.post("/api/effect-callback", json=payload)).status_code == 401
    assert (
        await ac.post("/api/effect-callback", json=payload, headers=_auth("loom_nope"))
    ).status_code == 401
    assert (
        await ac.post("/api/effect-callback", json=payload, headers=_auth(keys["dead"]))
    ).status_code == 401  # 已吊销 key 的明文同样 401（验签统一不区分原因）


# ---------- 匹配 / 孤儿 / 数据纪律 ----------


async def test_happy_matched_orphan_and_sparse_metrics(client, session_factory):
    ac, keys = client
    r = await ac.post(
        "/api/effect-callback",
        headers=_auth(keys["active"]),
        json={
            "source": "agent-1",
            "records": [
                {"content_id": "c1", "platform_post_id": "https://x/1",
                 "captured_at": TS1, "metrics": {"plays": 10, "likes": 2, "read_rate": 0.5}},
                {"content_id": "ghost-id", "platform_post_id": "https://x/2", "captured_at": TS2},
                {"content_id": "c2", "platform_post_id": "https://x/3", "captured_at": TS1},
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"received": 3, "matched": 1, "orphan": 2, "upserted": 0}
    assert await _count(session_factory) == 3
    assert await _count(session_factory, status=STATUS_MATCHED) == 1
    assert await _count(session_factory, status=STATUS_ORPHAN) == 2

    async with session_factory() as session:
        row = (await session.scalars(
            select(EffectRecord).where(EffectRecord.external_content_id == "c1")
        )).one()
        assert row.tenant_id == "t1"
        assert row.matched_content_id == "c1"
        assert row.received_by == keys["active_key_id"]
        # 稀疏 metrics：缺席键不得补 0。
        assert row.metrics == {"plays": 10, "likes": 2, "read_rate": 0.5}
        assert "comments" not in row.metrics and "conversions" not in row.metrics
        # discarded 成品不命中。
        c2 = (await session.scalars(
            select(EffectRecord).where(EffectRecord.external_content_id == "c2")
        )).one()
        assert c2.status == STATUS_ORPHAN and c2.tenant_id is None


async def test_customer_backfill_source_accepted(client, session_factory):
    ac, keys = client
    r = await ac.post(
        "/api/effect-callback",
        headers=_auth(keys["active"]),
        json={"source": "customer-backfill", "records": [
            {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1},
        ]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["matched"] == 1


# ---------- 幂等覆盖 / 时序追加 ----------


async def test_idempotent_overwrite_then_series_append(client, session_factory):
    ac, keys = client
    body = {"source": "agent-1", "records": [
        {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1,
         "metrics": {"plays": 1}},
    ]}
    hdr = _auth(keys["active"])
    assert (await ac.post("/api/effect-callback", headers=hdr, json=body)).json()["upserted"] == 0

    # 同 content_id + captured_at 重推（改指标）→ 幂等覆盖，不新增行。
    body["records"][0]["metrics"] = {"plays": 5, "likes": 9}
    body["records"][0]["platform_post_id"] = "p2"
    r = await ac.post("/api/effect-callback", headers=hdr, json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"received": 1, "matched": 1, "orphan": 0, "upserted": 1}
    assert await _count(session_factory, external_content_id="c1") == 1

    # 新采集点 → 追加为时序第二行。
    body["records"][0]["captured_at"] = TS2
    r = await ac.post("/api/effect-callback", headers=hdr, json=body)
    assert r.json()["upserted"] == 0
    assert await _count(session_factory, external_content_id="c1") == 2

    r = await ac.get("/api/admin/effects", params={"content_id": "c1", **OPS_Q})
    assert r.status_code == 200
    series = r.json()
    assert len(series) == 2
    # captured_at 升序（sqlite 往返丢 tz 标记，PG DateTime(tz) 保留；只核顺序）。
    assert series[0]["captured_at"].startswith("2026-09-01")
    assert series[1]["captured_at"].startswith("2026-09-02")
    # 第一行（TS1）已被覆盖为 plays=5。
    assert series[0]["metrics"] == {"plays": 5, "likes": 9}


async def test_duplicate_point_within_batch_rejected(client, session_factory):
    ac, keys = client
    r = await ac.post(
        "/api/effect-callback",
        headers=_auth(keys["active"]),
        json={"source": "agent-1", "records": [
            {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1},
            {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1},
        ]},
    )
    assert r.status_code == 422
    assert await _count(session_factory) == 0


# ---------- 校验 all-or-nothing ----------


@pytest.mark.parametrize("bad_record", [
    {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1, "metrics": {"followers": 1}},
    {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1, "metrics": {"plays": -3}},
    {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1, "metrics": {"read_rate": 1.5}},
    {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1, "metrics": {"plays": True}},
    {"content_id": "c1", "platform_post_id": "p", "captured_at": "2026-09-01T10:00:00"},
])
async def test_invalid_record_whole_batch_rejected(client, session_factory, bad_record):
    ac, keys = client
    r = await ac.post(
        "/api/effect-callback",
        headers=_auth(keys["active"]),
        json={"source": "agent-1", "records": [
            {"content_id": "c1", "platform_post_id": "p", "captured_at": TS2, "metrics": {"plays": 7}},
            bad_record,
        ]},
    )
    assert r.status_code == 422, r.text
    # 同批合法记录也不得落库（all-or-nothing）。
    assert await _count(session_factory) == 0


async def test_empty_records_and_missing_source_rejected(client):
    ac, keys = client
    hdr = _auth(keys["active"])
    assert (await ac.post("/api/effect-callback", headers=hdr,
                          json={"source": "a", "records": []})).status_code == 422
    assert (await ac.post("/api/effect-callback", headers=hdr,
                          json={"source": "", "records": [
                              {"content_id": "c1", "platform_post_id": "p", "captured_at": TS1}]})
            ).status_code == 422


# ---------- 只读队列 query actor 闸 ----------


async def test_orphan_queue_guards(client, session_factory):
    ac, keys = client
    await ac.post(
        "/api/effect-callback",
        headers=_auth(keys["active"]),
        json={"source": "agent-1", "records": [
            {"content_id": "ghost", "platform_post_id": "p", "captured_at": TS1},
        ]},
    )
    url = "/api/admin/effects/orphans"
    assert (await ac.get(url)).status_code == 422            # 缺 actor
    assert (await ac.get(url, params=CUSTOMER_Q)).status_code == 403
    assert (await ac.get(url, params=OPS_Q)).status_code == 200
    r = await ac.get(url, params=ADMIN_Q)
    assert r.status_code == 200
    assert len(r.json()) == 1 and r.json()[0]["status"] == STATUS_ORPHAN


async def test_series_requires_content_id_and_role(client):
    ac, _ = client
    # 缺 content_id → 422。
    assert (await ac.get("/api/admin/effects", params=OPS_Q)).status_code == 422
    # 客户越权 → 403。
    assert (
        await ac.get("/api/admin/effects", params={"content_id": "c1", **CUSTOMER_Q})
    ).status_code == 403
    # operations 正常，未推送时为空时序。
    r = await ac.get("/api/admin/effects", params={"content_id": "c1", **OPS_Q})
    assert r.status_code == 200 and r.json() == []
