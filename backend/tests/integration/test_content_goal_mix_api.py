"""Q44：内容目的配比健康度只读 API 的集成契约。

口径：近 30 天已签发 FCW 按 goal 计数，对比 Q25 字典的 ratio_min/max；
只读软提示，不阻断发证。覆盖窗界、租户/产品空间过滤、draft 排除、
健康五态、未映射目的计数、非法窗口与读闸。
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.final.final_whitelist.exit_guard import issue_scope
from app.final.final_whitelist.models import FinalContentWhitelist
from app.main import app
from app.product.condition.models import ContentGoal
from app.product.condition.seeds import CONTENT_GOAL_RATIO_DEFAULTS

TENANT = "tenant-q44"
PS = "ps-q44"
PATH = "/api/admin/content-goal-mix"
OPS = [("actor_id", "ops-1"), ("roles", "operations")]


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
        for code, (ratio_min, ratio_max) in CONTENT_GOAL_RATIO_DEFAULTS.items():
            session.add(
                ContentGoal(code=code, ratio_min=ratio_min, ratio_max=ratio_max)
            )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _issue(
    session: AsyncSession,
    *,
    goal: str,
    created_at: datetime,
    tenant_id: str = TENANT,
    product_space_id: str = PS,
    publish_status: str = "published",
) -> None:
    with issue_scope():
        session.add(
            FinalContentWhitelist(
                final_id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                product_space_id=product_space_id,
                pws_id="pws-1",
                pwc_id="pwc-1",
                pcp_id="pcp-1",
                csp_package_id="csp-1",
                cstp_package_id="cstp-1",
                cep_package_id="cep-1",
                platform="x",
                slot_id=f"slot-{uuid.uuid4()}",
                goal=goal,
                guards={},
                guards_passed=True,
                publish_status=publish_status,
                issued_by="ops-1",
                created_at=created_at,
            )
        )
        # mapper 守卫挂在 flush，不挂在 add；测试夹具在作用域内显式 flush。
        await session.flush()


async def _query(client, **params):
    payload = dict(OPS)
    payload["tenant_id"] = TENANT
    payload.update(params)
    return await client.get(PATH, params=payload)


async def test_window_and_filters_count_only_published_fcw_in_tenant_and_ps(
    client, session_factory
):
    async with session_factory() as session:
        # 窗内 5 条：ENG 3、CONV 1、EDU 1
        await _issue(session, goal="ENGAGEMENT", created_at=datetime(2026, 11, 1, tzinfo=UTC))
        await _issue(session, goal="ENGAGEMENT", created_at=datetime(2026, 11, 15, tzinfo=UTC))
        await _issue(session, goal="ENGAGEMENT", created_at=datetime(2026, 11, 23, 23, tzinfo=UTC))
        await _issue(session, goal="CONVERSION", created_at=datetime(2026, 11, 10, tzinfo=UTC))
        await _issue(session, goal="EDUCATION", created_at=datetime(2026, 11, 20, tzinfo=UTC))
        # 窗外（10/31）、异租户、异 PS、draft 均不计
        await _issue(session, goal="TRUST", created_at=datetime(2026, 10, 31, tzinfo=UTC))
        await _issue(
            session,
            goal="TRUST",
            created_at=datetime(2026, 11, 10, tzinfo=UTC),
            tenant_id="tenant-other",
        )
        await _issue(
            session,
            goal="RETENTION",
            created_at=datetime(2026, 11, 10, tzinfo=UTC),
            product_space_id="ps-other",
        )
        await _issue(
            session,
            goal="RETENTION",
            created_at=datetime(2026, 11, 10, tzinfo=UTC),
            publish_status="draft",
        )
        await session.commit()

    resp = await _query(
        client,
        date_from="2026-11-01",
        date_to="2026-11-23",
        product_space_id=PS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["window"] == {
        "date_from": "2026-11-01",
        "date_to": "2026-11-23",
        "days": 23,
    }
    assert body["total"] == 5
    assert body["unmapped_count"] == 0
    rows = {row["code"]: row for row in body["goals"]}
    assert rows["ENGAGEMENT"]["count"] == 3
    assert rows["ENGAGEMENT"]["actual_ratio"] == 0.6
    assert rows["ENGAGEMENT"]["health"] == "above"
    assert rows["CONVERSION"]["count"] == 1
    assert rows["CONVERSION"]["health"] == "within"
    assert rows["EDUCATION"]["count"] == 1
    assert rows["EDUCATION"]["health"] == "within"
    assert rows["TRUST"]["count"] == 0
    assert rows["TRUST"]["health"] == "below"
    assert rows["RETENTION"]["health"] == "below"
    assert {a["code"] for a in body["alerts"]} == {
        "ENGAGEMENT",
        "TRUST",
        "RETENTION",
    }
    engagement_alert = next(a for a in body["alerts"] if a["code"] == "ENGAGEMENT")
    assert engagement_alert["bound"] == 0.40
    trust_alert = next(a for a in body["alerts"] if a["code"] == "TRUST")
    assert trust_alert["bound"] == 0.15


async def test_archived_goal_is_unmapped_and_unconfigured_goals_do_not_alert(
    client, session_factory
):
    async with session_factory() as session:
        session.add(ContentGoal(code="LEGACY", status="archived"))
        await _issue(session, goal="ENGAGEMENT", created_at=datetime(2026, 11, 10, tzinfo=UTC))
        await _issue(session, goal="LEGACY", created_at=datetime(2026, 11, 11, tzinfo=UTC))
        await session.commit()

    body = (await _query(client, date_from="2026-11-01", date_to="2026-11-23")).json()
    assert body["total"] == 2
    assert body["unmapped_count"] == 1
    assert "LEGACY" not in {row["code"] for row in body["goals"]}


async def test_empty_window_is_all_no_data_with_no_false_alerts(client):
    body = (await _query(client, date_from="2026-11-01", date_to="2026-11-23")).json()
    assert body["total"] == 0
    assert body["alerts"] == []
    assert all(row["health"] == "no_data" for row in body["goals"])
    assert all(row["actual_ratio"] == 0.0 for row in body["goals"])


async def test_goal_without_bounds_is_unconfigured_not_below(client, session_factory):
    async with session_factory() as session:
        session.add(ContentGoal(code="UNBOUNDED"))
        await _issue(session, goal="UNBOUNDED", created_at=datetime(2026, 11, 10, tzinfo=UTC))
        await session.commit()

    frame = (await _query(client, date_from="2026-11-01", date_to="2026-11-23")).json()
    row = next(r for r in frame["goals"] if r["code"] == "UNBOUNDED")
    assert row["health"] == "unconfigured"
    assert "UNBOUNDED" not in {a["code"] for a in frame["alerts"]}


async def test_invalid_window_is_422_and_tenant_is_required(client):
    bad = await client.get(
        PATH,
        params=[*OPS, ("tenant_id", TENANT), ("date_from", "2026-11-23"), ("date_to", "2026-11-01")],
    )
    assert bad.status_code == 422, bad.text
    missing_tenant = await client.get(PATH, params=OPS)
    assert missing_tenant.status_code == 422, missing_tenant.text
    denied = await client.get(
        PATH,
        params=[("actor_id", "cust-1"), ("roles", "customer"), ("tenant_id", TENANT)],
    )
    assert denied.status_code == 403, denied.text
