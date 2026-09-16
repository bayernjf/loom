"""SLA 引擎集成：统一 /sla/run 接通升级/未来生效词补扫，看板 sla_state，错误隔离。"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.compliance_wordlist.models import ComplianceWordlistEntry
from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.sla.runner import run_jobs
from app.main import app
from app.product.modeling.models import OpsTodo

NOW = datetime.now(UTC)

PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
SLA_VIEW_PARAMS = [("actor_id", "pa-1"), ("roles", "platform_admin")]


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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_run_escalates_due_todos_and_reports_per_job(client, session_factory):
    async with session_factory() as session:
        session.add(OpsTodo(
            tenant_id="t1", todo_type="ops_assist", entity_type="c1_record",
            entity_id="c1", assignee_role="operations",
            due_at=NOW - timedelta(hours=1), created_at=NOW - timedelta(hours=73),
        ))
        session.add(OpsTodo(
            tenant_id="t1", todo_type="law_review", entity_type="law_review",
            entity_id="lr1", assignee_role="internal_compliance",
            due_at=NOW + timedelta(hours=10), created_at=NOW - timedelta(hours=38),
        ))
        await session.commit()

    resp = await client.post("/api/admin/sla/run", json={"actor": PLATFORM_ADMIN})
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["todo_escalation"]["changed"] == 1
    assert report["wordlist_activation"]["changed"] == 0

    async with session_factory() as session:
        todos = (await session.scalars(select(OpsTodo).order_by(OpsTodo.created_at))).all()
        assert todos[0].status == "escalated"
        assert todos[1].status == "open"
        actions = (await session.scalars(
            select(AuditLog.action).where(AuditLog.entity_type == "ops_todo")
        )).all()
        assert actions == ["c1.todo_escalated"]

    board = await client.get(
        "/api/admin/sla/todos",
        params=[*SLA_VIEW_PARAMS, ("status", "all")],
    )
    assert board.status_code == 200
    states = {row["todo_type"]: row["sla_state"] for row in board.json()}
    assert states["ops_assist"] == "red"
    assert states["law_review"] == "yellow"


async def test_todo_board_requires_actor_and_platform_admin(client):
    # Q108：看板补 RBAC——缺 actor_id query → 422；非 platform_admin → 403。
    assert (await client.get("/api/admin/sla/todos")).status_code == 422
    for role in ["operations", "internal_compliance", "customer"]:
        r = await client.get(
            "/api/admin/sla/todos",
            params=[("actor_id", "u1"), ("roles", role)],
        )
        assert r.status_code == 403, role
    r = await client.get("/api/admin/sla/todos", params=SLA_VIEW_PARAMS)
    assert r.status_code == 200
    assert r.json() == []  # 默认仅 open


async def test_todo_board_rejects_unknown_status(client):
    r = await client.get(
        "/api/admin/sla/todos",
        params=[*SLA_VIEW_PARAMS, ("status", "bogus")],
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "unknown todo status: bogus"


async def test_todo_board_filters_and_derives_sla_state(client, session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                OpsTodo(
                    tenant_id="t1", todo_type="pws_ready", entity_type="product_space",
                    entity_id="ps-open", assignee_role="operations",
                    due_at=NOW + timedelta(hours=10), created_at=NOW,
                ),
                OpsTodo(
                    tenant_id="t1", todo_type="law_review", entity_type="law_review",
                    entity_id="lr-yellow", assignee_role="internal_compliance",
                    due_at=NOW + timedelta(hours=10), created_at=NOW - timedelta(hours=38),
                ),
                OpsTodo(
                    tenant_id="t2", todo_type="review_pwc_combo", entity_type="skill_candidate",
                    entity_id="sc-red", assignee_role="product_reviewer",
                    due_at=NOW - timedelta(hours=1), created_at=NOW - timedelta(hours=73),
                ),
                OpsTodo(
                    tenant_id="t1", todo_type="ops_assist_category", entity_type="c1_record",
                    entity_id="c1-esc", assignee_role="operations", status="escalated",
                    escalated_at=NOW - timedelta(hours=1),
                    due_at=NOW - timedelta(hours=2), created_at=NOW - timedelta(hours=74),
                ),
                OpsTodo(
                    tenant_id="t1", todo_type="wordlist_rescan", entity_type="pws",
                    entity_id="pws-done", assignee_role="internal_compliance", status="resolved",
                    resolution="applied", resolved_at=NOW - timedelta(hours=2),
                    due_at=NOW + timedelta(days=2), created_at=NOW - timedelta(days=3),
                ),
            ]
        )
        await session.commit()

    async def board(status: str | None = None):
        params = list(SLA_VIEW_PARAMS)
        if status is not None:
            params.append(("status", status))
        r = await client.get("/api/admin/sla/todos", params=params)
        assert r.status_code == 200, r.text
        return r.json()

    all_rows = await board("all")
    assert len(all_rows) == 5
    # due_at 升序。
    dues = [row["due_at"] for row in all_rows]
    assert dues == sorted(dues)
    states = {row["entity_id"]: row["sla_state"] for row in all_rows}
    assert states == {
        "ps-open": "green",
        "lr-yellow": "yellow",
        "sc-red": "red",
        "c1-esc": "red",
        "pws-done": "resolved",
    }

    open_rows = await board()  # 默认 open
    assert {row["entity_id"] for row in open_rows} == {"ps-open", "lr-yellow", "sc-red"}
    assert {row["entity_id"] for row in await board("escalated")} == {"c1-esc"}
    resolved_rows = await board("resolved")
    assert {row["entity_id"] for row in resolved_rows} == {"pws-done"}
    assert resolved_rows[0]["sla_state"] == "resolved"


async def test_future_effective_word_activates_and_rescans(client, session_factory):
    async with session_factory() as session:
        session.add(ComplianceWordlistEntry(
            word="未来词", level="critical", action="ban", layer="base",
            status="active", effective_from=NOW - timedelta(minutes=5), activated_at=None,
        ))
        await session.commit()

    resp = await client.post("/api/admin/sla/run", json={"actor": PLATFORM_ADMIN})
    assert resp.json()["wordlist_activation"]["changed"] == 1
    resp2 = await client.post("/api/admin/sla/run", json={"actor": PLATFORM_ADMIN})
    assert resp2.json()["wordlist_activation"]["changed"] == 0

    async with session_factory() as session:
        entry = (await session.scalars(select(ComplianceWordlistEntry))).first()
        assert entry.activated_at is not None


async def test_runner_isolates_failing_job(session_factory, monkeypatch):
    async def bad(session, now):
        raise RuntimeError("boom")

    async def good(session, now):
        return 7

    from app.core.sla import runner as runner_mod

    monkeypatch.setattr(runner_mod, "JOBS", [("bad", bad), ("good", good)])
    report = await run_jobs(session_factory, now=NOW)
    assert "error" in report["bad"]
    assert report["good"] == {"changed": 7}
