"""Q101 客户合规风控页租户只读聚合端点集成测试。

读路径纪律同 Q98–Q100：不触发 Q95 准入门、不 writeAudit，未知租户 200 空
items；仅 active frozen 快照，每市场取最新一行 CCR 后跨市场从严，法审一
PWS 一条。直接 ORM 播种（聚合只消费报告/法审行，不依赖段 1–6 链路）。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.tenants.models import Tenant
from app.decision.compliance_center import ccr_rules
from app.decision.compliance_center.models import CcrReport, LawReview
from app.main import app
from app.product.product_intake.models import (
    ProductIntakeApplication,
    ProductSpace,
)
from app.product.whitelist_center.models import PwsSnapshot


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
                Tenant(tenant_id="t1", name="试点客户", plan="basic", status="active"),
                Tenant(tenant_id="t2", name="第二客户", plan="basic", status="active"),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _snapshot(session_factory, *, tenant, product_name, active=True, status="frozen"):
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id=tenant, status="stored", profile={"product_name": product_name}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id=tenant, intake_id=intake.intake_id, profile_snapshot={}
        )
        session.add(ps)
        await session.flush()
        snap = PwsSnapshot(
            tenant_id=tenant,
            product_space_id=ps.product_space_id,
            version="v1",
            status=status,
            is_active=active,
            fingerprint=f"fp-{ps.product_space_id}",
            snapshot={},
            readiness={},
        )
        session.add(snap)
        await session.commit()
        return ps.product_space_id, snap.pws_id


def _report(
    tenant,
    ps_id,
    pws_id,
    *,
    status,
    country=None,
    blocked=False,
    bans=None,
    downgrades=None,
    minutes_ago=0,
):
    return CcrReport(
        tenant_id=tenant,
        product_space_id=ps_id,
        pws_id=pws_id,
        country=country,
        status=status,
        block_required=blocked,
        hits={"bans": bans or [], "downgrades": downgrades or []},
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


async def test_overview_empty_for_unknown_tenant(client):
    r = await client.get("/api/compliance/overview", params={"tenant_id": "ghost"})
    assert r.status_code == 200
    assert r.json() == {"items": []}


async def test_overview_aggregates_latest_per_market_and_scopes(client, session_factory):
    ps_a, pws_a = await _snapshot(
        session_factory, tenant="t1", product_name="修护精华"
    )
    ps_b, pws_b = await _snapshot(
        session_factory, tenant="t1", product_name="洁净面霜"
    )
    # t1 第三个快照：superseded 必须被排除，即便其报告 blocked
    ps_c, pws_c = await _snapshot(
        session_factory, tenant="t1", product_name="旧版产品",
        active=False, status="superseded",
    )
    # t2 active blocked：租户隔离必须排除
    ps_t2, pws_t2 = await _snapshot(
        session_factory, tenant="t2", product_name="他租户产品"
    )

    async with session_factory() as session:
        session.add_all(
            [
                # pws_a：CN 先 blocked 后重跑 clean（最新取 clean）；US 最新仍 blocked → 行从严 blocked
                _report("t1", ps_a, pws_a, status=ccr_rules.REPORT_BLOCKED,
                        country="CN", blocked=True, bans=[{"word": "旧禁词"}],
                        minutes_ago=20),
                _report("t1", ps_a, pws_a, status=ccr_rules.REPORT_CLEAN,
                        country="CN", minutes_ago=5),
                _report("t1", ps_a, pws_a, status=ccr_rules.REPORT_BLOCKED,
                        country="US", blocked=True, bans=[{"word": "FDA"}],
                        minutes_ago=10),
                # pws_b：仅底座 downgrade_pending
                _report("t1", ps_b, pws_b,
                        status=ccr_rules.REPORT_DOWNGRADE_PENDING,
                        downgrades=[{"word": "焕白", "downgrade_target": "提亮"}],
                        minutes_ago=3),
                # 旧版/他租户的 blocked 不得污染 t1 总览
                _report("t1", ps_c, pws_c, status=ccr_rules.REPORT_BLOCKED,
                        blocked=True, minutes_ago=1),
                _report("t2", ps_t2, pws_t2, status=ccr_rules.REPORT_BLOCKED,
                        blocked=True, minutes_ago=1),
                # pws_a 法审一条（pending）
                LawReview(
                    tenant_id="t1", product_space_id=ps_a, pws_id=pws_a,
                    domain="medical", status="pending",
                ),
            ]
        )
        await session.commit()

    r = await client.get("/api/compliance/overview", params={"tenant_id": "t1"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 2  # 仅两个 active frozen；superseded 与 t2 均排除
    by_pws = {item["pws_id"]: item for item in items}

    a = by_pws[pws_a]
    assert a["product_name"] == "修护精华"
    assert a["ccr"]["worst_status"] == "blocked"
    assert a["ccr"]["block_required"] is True
    markets = {m["country"]: m for m in a["ccr"]["markets"]}
    assert set(markets) == {"CN", "US"}
    assert markets["CN"]["status"] == "clean"
    assert markets["CN"]["bans"] == []
    assert markets["US"]["status"] == "blocked"
    assert markets["US"]["bans"][0]["word"] == "FDA"
    assert a["law_review"]["status"] == "pending"
    assert a["law_review"]["domain"] == "medical"
    assert a["law_review"]["conclusion"] is None

    b = by_pws[pws_b]
    assert b["ccr"]["worst_status"] == "downgrade_pending"
    assert b["ccr"]["block_required"] is False
    base = b["ccr"]["markets"][0]
    assert base["country"] is None
    assert base["downgrades"][0]["downgrade_target"] == "提亮"
    assert b["law_review"] is None


async def test_overview_no_reports_yields_null_ccr(client, session_factory):
    _ps, pws_id = await _snapshot(
        session_factory, tenant="t1", product_name="未清洗产品"
    )
    r = await client.get("/api/compliance/overview", params={"tenant_id": "t1"})
    item = r.json()["items"][0]
    assert item["pws_id"] == pws_id
    assert item["ccr"] is None
    assert item["law_review"] is None


async def test_overview_rejects_empty_tenant(client):
    r = await client.get("/api/compliance/overview", params={"tenant_id": ""})
    assert r.status_code == 422
