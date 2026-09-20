"""Q127（段13/Q60a）集成测试：孤儿效果记录人工认领 POST /api/admin/effects/claims。

口径（02 C1.71，接缝按推荐甲拍板）：
- 管理面写口 actor 在体、服务层 operations 闸（客户/platform_admin 403，同 Q125）；
- 入口记录须为当前 orphan（未知 404、非 orphan 409），目标成品须存在且非
  discarded（未知 404、discarded 409）；
- upsert external_content_id→content_id 持久映射（表 effect_claims）：认领后
  同 ID 的后续推送（幂等覆盖与新采集点）按映射 matched，不回落孤儿；
- 回填该 ID 下全部 orphan 行与历史人工认领行（改绑重指），自动 matched 行不动；
- 行级溯源 claimed_by/claimed_at；审计 effect.claimed（tenant _platform）。

create_all 不跑迁移种子；成品由本文件 fixture 自插，Agent Key 用于造孤儿推送。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_DISCARDED, CONTENT_READY, ContentProduct
from app.core.actor import Actor
from app.core.api_keys.service import issue_key
from app.core.db import Base, get_session
from app.core.effects.models import (
    STATUS_MATCHED,
    STATUS_ORPHAN,
    EffectClaim,
    EffectRecord,
)
from app.core.rbac import PLATFORM_ADMIN
from app.main import app

OPS = {"id": "ops-1", "roles": ["operations"]}
OPS_Q = {"actor_id": "ops-1", "roles": ["operations"]}
ADMIN_BODY = {"id": "admin-1", "roles": [PLATFORM_ADMIN]}
CUSTOMER_BODY = {"id": "cust-1", "roles": []}

TS1 = "2026-09-01T10:00:00Z"
TS2 = "2026-09-02T10:00:00Z"
TS3 = "2026-09-03T10:00:00Z"


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
        _row, plain = await issue_key(
            session, "agent-1", Actor(id="admin-1", roles=[PLATFORM_ADMIN])
        )
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
        key = plain
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, key


async def _push(ac, key, content_id, ts, *, source="agent-1"):
    return await ac.post(
        "/api/effect-callback",
        headers={"Authorization": f"Bearer {key}"},
        json={"source": source, "records": [
            {"content_id": content_id, "platform_post_id": "p", "captured_at": ts},
        ]},
    )


async def _orphan_record_id(session_factory, external_id="ghost") -> str:
    async with session_factory() as session:
        row = (await session.scalars(
            select(EffectRecord).where(
                EffectRecord.external_content_id == external_id,
                EffectRecord.status == STATUS_ORPHAN,
            )
        )).first()
        assert row is not None
        return row.record_id


async def _count(session_factory, model, **where) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(model)
        if where:
            stmt = stmt.filter_by(**where)
        return (await session.execute(stmt)).scalar_one()


# ---------- 认领主流程 ----------


async def test_claim_binds_orphan_and_clears_queue(client, session_factory):
    ac, key = client
    r = await _push(ac, key, "ghost", TS1)
    assert r.json()["orphan"] == 1
    record_id = await _orphan_record_id(session_factory)

    r = await ac.post("/api/admin/effects/claims", json={
        "record_id": record_id, "content_id": "c1", "actor": OPS,
    })
    assert r.status_code == 200, r.text
    view = r.json()
    assert view == {
        "external_content_id": "ghost",
        "content_id": "c1",
        "claimed_by": "ops-1",
        "claimed_at": view["claimed_at"],
        "updated_rows": 1,
    }
    assert view["claimed_at"].startswith("2026-09-")

    # 孤儿队列清空；c1 时序出现该行且带认领溯源。
    r = await ac.get("/api/admin/effects/orphans", params=OPS_Q)
    assert r.json() == []
    r = await ac.get("/api/admin/effects", params={"content_id": "c1", **OPS_Q})
    series = r.json()
    assert len(series) == 1
    assert series[0]["status"] == STATUS_MATCHED
    assert series[0]["matched_content_id"] == "c1"
    assert series[0]["tenant_id"] == "t1"
    assert series[0]["claimed_by"] == "ops-1"
    assert series[0]["claimed_at"] is not None

    # 持久映射落表。
    assert await _count(session_factory, EffectClaim,
                        external_content_id="ghost", content_id="c1") == 1


async def test_claim_makes_later_pushes_match_never_orphan(client, session_factory):
    ac, key = client
    await _push(ac, key, "ghost", TS1)
    record_id = await _orphan_record_id(session_factory)
    assert (await ac.post("/api/admin/effects/claims", json={
        "record_id": record_id, "content_id": "c1", "actor": OPS,
    })).status_code == 200

    # 新采集点：自动按认领映射 matched，不进孤儿队列。
    r = await _push(ac, key, "ghost", TS2)
    assert r.status_code == 200
    assert r.json() == {"received": 1, "matched": 1, "orphan": 0, "upserted": 0}
    # 同采集点幂等覆盖：仍 matched，不冲回孤儿。
    r = await _push(ac, key, "ghost", TS2)
    assert r.json() == {"received": 1, "matched": 1, "orphan": 0, "upserted": 1}

    assert await _count(session_factory, EffectRecord, status=STATUS_ORPHAN) == 0
    r = await ac.get("/api/admin/effects", params={"content_id": "c1", **OPS_Q})
    assert len(r.json()) == 2


async def test_rebind_after_old_target_discarded_repoints_claimed_rows(
    client, session_factory
):
    ac, key = client
    await _push(ac, key, "ghost", TS1)
    rid = await _orphan_record_id(session_factory)
    await ac.post("/api/admin/effects/claims", json={
        "record_id": rid, "content_id": "c1", "actor": OPS,
    })
    # 旧目标 c1 被作废；映射兜底失效，新采集点回落孤儿。
    async with session_factory() as session:
        c1 = await session.get(ContentProduct, "c1")
        c1.status = CONTENT_DISCARDED
        await session.commit()
    r = await _push(ac, key, "ghost", TS2)
    assert r.json()["orphan"] == 1

    # 用新孤儿行重新认领到 c3（改绑）：历史认领行 + 新孤儿行全部重指 c3。
    rid2 = await _orphan_record_id(session_factory)
    r = await ac.post("/api/admin/effects/claims", json={
        "record_id": rid2, "content_id": "c3", "actor": OPS,
    })
    assert r.status_code == 200, r.text
    assert r.json()["updated_rows"] == 2

    async with session_factory() as session:
        claim = await session.get(EffectClaim, "ghost")
        assert claim.content_id == "c3"
        rows = (await session.scalars(
            select(EffectRecord).where(EffectRecord.external_content_id == "ghost")
        )).all()
        assert len(rows) == 2
        assert all(row.matched_content_id == "c3" for row in rows)
        assert all(row.tenant_id == "t2" for row in rows)
        assert all(row.status == STATUS_MATCHED for row in rows)


# ---------- 校验 / 角色闸 ----------


async def test_claim_unknown_record_404(client):
    ac, _ = client
    r = await ac.post("/api/admin/effects/claims", json={
        "record_id": "nope", "content_id": "c1", "actor": OPS,
    })
    assert r.status_code == 404


async def test_claim_non_orphan_record_409(client, session_factory):
    ac, key = client
    await _push(ac, key, "c1", TS1)  # 自动 matched，非孤儿
    async with session_factory() as session:
        row = (await session.scalars(
            select(EffectRecord).where(EffectRecord.external_content_id == "c1")
        )).one()
        matched_id = row.record_id
    r = await ac.post("/api/admin/effects/claims", json={
        "record_id": matched_id, "content_id": "c3", "actor": OPS,
    })
    assert r.status_code == 409


async def test_claim_unknown_target_404(client, session_factory):
    ac, key = client
    await _push(ac, key, "ghost", TS1)
    rid = await _orphan_record_id(session_factory)
    r = await ac.post("/api/admin/effects/claims", json={
        "record_id": rid, "content_id": "nope", "actor": OPS,
    })
    assert r.status_code == 404
    # 整批动作不落半成品：无映射、孤儿仍在。
    assert await _count(session_factory, EffectClaim) == 0
    assert await _count(session_factory, EffectRecord, status=STATUS_ORPHAN) == 1


async def test_claim_discarded_target_409(client, session_factory):
    ac, key = client
    await _push(ac, key, "ghost", TS1)
    rid = await _orphan_record_id(session_factory)
    r = await ac.post("/api/admin/effects/claims", json={
        "record_id": rid, "content_id": "c2", "actor": OPS,
    })
    assert r.status_code == 409
    assert await _count(session_factory, EffectClaim) == 0


async def test_claim_role_guard_customer_and_admin_403(client, session_factory):
    ac, key = client
    await _push(ac, key, "ghost", TS1)
    rid = await _orphan_record_id(session_factory)
    payload_tail = {"record_id": rid, "content_id": "c1"}
    assert (await ac.post("/api/admin/effects/claims", json={
        **payload_tail, "actor": CUSTOMER_BODY,
    })).status_code == 403
    # 写口仅 operations（同 Q125 publish-info），platform_admin 同样 403。
    assert (await ac.post("/api/admin/effects/claims", json={
        **payload_tail, "actor": ADMIN_BODY,
    })).status_code == 403
    assert await _count(session_factory, EffectClaim) == 0
