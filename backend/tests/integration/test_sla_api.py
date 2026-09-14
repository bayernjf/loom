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

    resp = await client.post("/api/admin/sla/run")
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

    board = await client.get("/api/admin/sla/todos", params={"status": "all"})
    states = {row["todo_type"]: row["sla_state"] for row in board.json()}
    assert states["ops_assist"] == "red"
    assert states["law_review"] == "yellow"


async def test_future_effective_word_activates_and_rescans(client, session_factory):
    async with session_factory() as session:
        session.add(ComplianceWordlistEntry(
            word="未来词", level="critical", action="ban", layer="base",
            status="active", effective_from=NOW - timedelta(minutes=5), activated_at=None,
        ))
        await session.commit()

    resp = await client.post("/api/admin/sla/run")
    assert resp.json()["wordlist_activation"]["changed"] == 1
    resp2 = await client.post("/api/admin/sla/run")
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
