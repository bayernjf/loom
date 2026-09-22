"""Q162 客户合规风控页只读扩展端点集成测试。

覆盖三件套：① CCR 分市场历史列表/详情（分页甲案、tenant 收窄、越权 404）；
② 法审记录只读 + 服务端派生 SLA（normal/overdue/resolved）；③ 客户侧只读词库
（仅 active、level/layer 过滤）。读路径纪律同 Q101：无闸、不 writeAudit、未知租户空。
直接 ORM 播种（CcrReport/LawReview 的外键列在 ORM 层为纯 String，in-memory 不强制 FK）。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.compliance_wordlist.models import ComplianceWordlistEntry
from app.core.db import Base, get_session
from app.core.tenants.models import Tenant
from app.decision.compliance_center import ccr_rules
from app.decision.compliance_center.models import CcrReport, LawReview
from app.main import app


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
                Tenant(tenant_id="t1", name="客户甲", plan="basic", status="active"),
                Tenant(tenant_id="t2", name="客户乙", plan="basic", status="active"),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _report(
    tenant,
    pws_id,
    *,
    status,
    country=None,
    blocked=False,
    minutes_ago=0,
):
    return CcrReport(
        tenant_id=tenant,
        product_space_id="ps-" + pws_id,
        pws_id=pws_id,
        country=country,
        status=status,
        block_required=blocked,
        hits={"bans": [{"word": "FDA"}] if blocked else [], "downgrades": []},
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


async def test_ccr_history_empty_for_unknown_tenant(client):
    r = await client.get("/api/compliance/ccr-history", params={"tenant_id": "ghost"})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_ccr_history_pagination_and_filters(client, session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                _report("t1", "pws-a", status=ccr_rules.REPORT_CLEAN, minutes_ago=30),
                _report("t1", "pws-a", status=ccr_rules.REPORT_BLOCKED,
                        country="CN", blocked=True, minutes_ago=20),
                _report("t1", "pws-a", status=ccr_rules.REPORT_CLEAN,
                        country="CN", minutes_ago=10),
                _report("t1", "pws-b", status=ccr_rules.REPORT_DOWNGRADE_PENDING,
                        minutes_ago=5),
                # 他租户不得污染
                _report("t2", "pws-a", status=ccr_rules.REPORT_BLOCKED,
                        blocked=True, minutes_ago=1),
            ]
        )
        await session.commit()

    # 默认分页：t1 共 4 条，时间倒序。
    r = await client.get("/api/compliance/ccr-history", params={"tenant_id": "t1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 4
    assert len(body["items"]) == 4
    times = [it["created_at"] for it in body["items"]]
    assert times == sorted(times, reverse=True)

    # pws_id 过滤。
    r = await client.get(
        "/api/compliance/ccr-history", params={"tenant_id": "t1", "pws_id": "pws-b"}
    )
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["pws_id"] == "pws-b"

    # country 过滤（仅 CN）。
    r = await client.get(
        "/api/compliance/ccr-history", params={"tenant_id": "t1", "country": "CN"}
    )
    assert r.json()["total"] == 2
    assert all(it["country"] == "CN" for it in r.json()["items"])

    # limit/offset 甲案。
    r = await client.get(
        "/api/compliance/ccr-history",
        params={"tenant_id": "t1", "limit": 2, "offset": 0},
    )
    assert r.json()["total"] == 4
    assert len(r.json()["items"]) == 2


async def test_ccr_detail_scoped_by_tenant(client, session_factory):
    async with session_factory() as session:
        rep = _report("t1", "pws-a", status=ccr_rules.REPORT_BLOCKED,
                      country="CN", blocked=True, minutes_ago=10)
        session.add(rep)
        await session.commit()
        ccr_id = rep.ccr_id

    # 本租户可读，含 hits 完整 JSON。
    r = await client.get(
        f"/api/compliance/ccr/{ccr_id}", params={"tenant_id": "t1"}
    )
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["ccr_id"] == ccr_id
    assert detail["hits"]["bans"][0]["word"] == "FDA"
    assert detail["block_required"] is True

    # 他租户 404（租户收窄）。
    r = await client.get(
        f"/api/compliance/ccr/{ccr_id}", params={"tenant_id": "t2"}
    )
    assert r.status_code == 404

    # 未知 ccr_id 404。
    r = await client.get(
        "/api/compliance/ccr/nope", params={"tenant_id": "t1"}
    )
    assert r.status_code == 404


async def test_law_reviews_sla_derived(client, session_factory):
    async with session_factory() as session:
        now = datetime.now(UTC)
        # pending 未过期（1h 前创建，剩 ~47h）。
        session.add(LawReview(
            tenant_id="t1", product_space_id="ps-a", pws_id="pws-a",
            domain="medical", status=ccr_rules.LAW_PENDING,
            created_at=now - timedelta(hours=1),
        ))
        # pending 已超 48h（49h 前创建）→ overdue。
        session.add(LawReview(
            tenant_id="t1", product_space_id="ps-b", pws_id="pws-b",
            domain="financial", status=ccr_rules.LAW_PENDING,
            created_at=now - timedelta(hours=49),
        ))
        # 已决 → resolved、remaining=None。
        session.add(LawReview(
            tenant_id="t1", product_space_id="ps-c", pws_id="pws-c",
            domain="children", status=ccr_rules.LAW_APPROVED,
            conclusion="通过", decided_by="lc-1",
            decided_at=now - timedelta(hours=2),
            created_at=now - timedelta(hours=50),
        ))
        # 他租户 pending 不得出现。
        session.add(LawReview(
            tenant_id="t2", product_space_id="ps-d", pws_id="pws-d",
            domain="medical", status=ccr_rules.LAW_PENDING,
        ))
        await session.commit()

    r = await client.get("/api/compliance/law-reviews", params={"tenant_id": "t1"})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 3  # t2 排除
    by_domain = {row["domain"]: row for row in rows}

    assert by_domain["medical"]["sla_state"] == "normal"
    assert by_domain["medical"]["sla_remaining_seconds"] is not None
    assert 46 * 3600 < by_domain["medical"]["sla_remaining_seconds"] < 48 * 3600

    assert by_domain["financial"]["sla_state"] == "overdue"
    assert by_domain["financial"]["sla_remaining_seconds"] == 0

    assert by_domain["children"]["sla_state"] == "resolved"
    assert by_domain["children"]["sla_remaining_seconds"] is None
    assert by_domain["children"]["conclusion"] == "通过"


async def test_customer_wordlist_active_only_and_filters(client, session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                ComplianceWordlistEntry(
                    word="FDA", level="critical", action="ban",
                    country="US", layer="country", status="active",
                ),
                ComplianceWordlistEntry(
                    word="焕白", level="high", action="downgrade",
                    country=None, layer="base", status="active",
                ),
                # archived 不得出现。
                ComplianceWordlistEntry(
                    word="旧词", level="high", action="ban",
                    country=None, layer="base", status="archived",
                ),
            ]
        )
        await session.commit()

    # 默认：仅 active。
    r = await client.get("/api/compliance/wordlist")
    assert r.status_code == 200, r.text
    words = {e["word"] for e in r.json()}
    assert words == {"FDA", "焕白"}
    # 不暴露管理面字段（entry_id 等）。
    assert "entry_id" not in r.json()[0]

    # level 过滤。
    r = await client.get("/api/compliance/wordlist", params={"level": "critical"})
    assert {e["word"] for e in r.json()} == {"FDA"}

    # layer 过滤。
    r = await client.get("/api/compliance/wordlist", params={"layer": "base"})
    assert {e["word"] for e in r.json()} == {"焕白"}
