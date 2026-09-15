"""M12 驾驶舱只读聚合集成测试（Q92）：Token 成本 + 人工审核工作量。

内存 SQLite + httpx ASGI 直插 skill_runs/skill_candidates/ops_todos，
只测聚合口径与 RBAC；驾驶舱只读，不产生任何写入。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.skill7.models import SkillCandidate, SkillRun
from app.main import app
from app.product.modeling.models import OpsTodo

NOW = datetime.now(UTC)
TODAY = NOW.date()

PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
OPERATIONS = {"id": "op-1", "roles": ["operations"]}


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


def _run(
    *,
    skill_id: str,
    status: str = "succeeded",
    source: str = "manual",
    model_id: str | None = "synthetic",
    at: datetime,
    input_tokens: int | None = 100,
    output_tokens: int | None = 50,
    input_cost: float | None = 0.001,
    output_cost: float | None = 0.002,
    currency_code: str | None = "USD",
) -> SkillRun:
    return SkillRun(
        skill_id=skill_id,
        wf_id="WF-04",
        status=status,
        source=source,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost=input_cost,
        output_cost=output_cost,
        currency_code=currency_code,
        created_at=at,
    )


def _candidate(
    *,
    target_type: str,
    state: str,
    created: datetime,
    index: int,
    reviewed_at: datetime | None = None,
) -> SkillCandidate:
    return SkillCandidate(
        run_id="run-seed",
        candidate_index=index,
        skill_id="PWC-BUILDER",
        wf_id="WF-04",
        target_type=target_type,
        payload={"x": 1},
        state=state,
        created_at=created,
        reviewed_at=reviewed_at,
    )


def _todo(
    *,
    todo_type: str,
    status: str = "open",
    due: datetime | None = None,
    resolved_at: datetime | None = None,
) -> OpsTodo:
    return OpsTodo(
        tenant_id="t1",
        todo_type=todo_type,
        entity_type="x",
        entity_id="x1",
        status=status,
        due_at=due or (NOW + timedelta(hours=10)),
        resolved_at=resolved_at,
        created_at=NOW - timedelta(hours=1),
    )


# ---------- Token 成本驾驶舱 ----------


async def test_token_cost_requires_actor_and_admin_role(client):
    resp = await client.get("/api/admin/dashboards/token-cost")
    assert resp.status_code == 422

    resp = await client.get(
        "/api/admin/dashboards/token-cost",
        params={"actor_id": OPERATIONS["id"], "roles": OPERATIONS["roles"]},
    )
    assert resp.status_code == 403


async def test_token_cost_default_window_groups_by_day_model_and_skill(
    client, session_factory
):
    async with session_factory() as session:
        session.add_all([
            _run(skill_id="CAT-RECOG", at=NOW - timedelta(days=1, hours=1)),
            _run(
                skill_id="CAT-RECOG",
                at=NOW - timedelta(days=1, hours=2),
                input_tokens=200,
                output_tokens=100,
                input_cost=0.002,
                output_cost=0.004,
            ),
            _run(
                skill_id="PWC-BUILDER",
                model_id="synthetic-embedding",
                currency_code="USD",
                at=NOW - timedelta(hours=2),
                input_cost=0.0,
                output_cost=0.0,
            ),
            # 不计费：requested 补货行无 model，failed 行进失败单列
            _run(
                skill_id="PWC-BUILDER",
                status="requested",
                source="restock_auto",
                model_id=None,
                at=NOW - timedelta(hours=3),
                input_tokens=None,
                output_tokens=None,
                input_cost=None,
                output_cost=None,
                currency_code=None,
            ),
            _run(
                skill_id="PWC-BUILDER",
                status="failed",
                at=NOW - timedelta(hours=4),
                input_tokens=None,
                output_tokens=None,
                input_cost=None,
                output_cost=None,
                currency_code=None,
            ),
            # 窗口外（31 天前）
            _run(skill_id="CAT-RECOG", at=NOW - timedelta(days=31)),
        ])
        await session.commit()

    resp = await client.get(
        "/api/admin/dashboards/token-cost",
        params={"actor_id": PLATFORM_ADMIN["id"], "roles": PLATFORM_ADMIN["roles"]},
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()

    assert report["window"] == {
        "from": (TODAY - timedelta(days=29)).isoformat(),
        "to": TODAY.isoformat(),
    }
    by_key = {(row["date"], row["model_id"]): row for row in report["daily"]}
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    row = by_key[(yesterday, "synthetic")]
    assert row["runs"] == 2
    assert row["input_tokens"] == 300
    assert row["output_tokens"] == 150
    assert row["total_cost"] == 0.009
    assert row["currency_code"] == "USD"

    skills = {row["skill_id"]: row for row in report["by_skill"]}
    assert skills["CAT-RECOG"]["runs"] == 2
    assert skills["PWC-BUILDER"]["runs"] == 1
    assert skills["PWC-BUILDER"]["total_cost"] == 0.0

    assert report["failed_by_skill"] == [
        {"skill_id": "PWC-BUILDER", "failed_runs": 1}
    ]
    assert report["totals"] == {
        "runs": 3,
        "input_tokens": 400,
        "output_tokens": 200,
        "failed_runs": 1,
    }


async def test_token_cost_separates_currencies_without_conversion(
    client, session_factory
):
    async with session_factory() as session:
        session.add_all([
            _run(skill_id="S1", currency_code="USD", at=NOW - timedelta(hours=1)),
            _run(
                skill_id="S1",
                currency_code="EUR",
                input_cost=0.01,
                output_cost=0.02,
                at=NOW - timedelta(hours=1),
            ),
        ])
        await session.commit()

    resp = await client.get(
        "/api/admin/dashboards/token-cost",
        params=[
            ("actor_id", PLATFORM_ADMIN["id"]),
            ("roles", PLATFORM_ADMIN["roles"][0]),
            ("date_from", TODAY.isoformat()),
            ("date_to", TODAY.isoformat()),
        ],
    )
    assert resp.status_code == 200, resp.text
    currencies = {row["currency_code"] for row in resp.json()["daily"]}
    assert currencies == {"USD", "EUR"}


async def test_token_cost_rejects_bad_window_and_bad_date(client):
    params = [
        ("actor_id", PLATFORM_ADMIN["id"]),
        ("roles", PLATFORM_ADMIN["roles"][0]),
        ("date_from", "2026-09-10"),
        ("date_to", "2026-09-01"),
    ]
    resp = await client.get("/api/admin/dashboards/token-cost", params=params)
    assert resp.status_code == 422

    params[2] = ("date_from", "not-a-date")
    resp = await client.get("/api/admin/dashboards/token-cost", params=params)
    assert resp.status_code == 422


# ---------- 人工审核工作量驾驶舱 ----------


async def test_review_workload_backlog_snapshot_and_window_output(
    client, session_factory
):
    async with session_factory() as session:
        session.add_all([
            # 候选积压：pwc_combo 两条（新老各一），c7_layer4 一条；applied 不计积压
            _candidate(
                target_type="pwc_combo",
                state="pending_review",
                index=1,
                created=NOW - timedelta(hours=2),
            ),
            _candidate(
                target_type="pwc_combo",
                state="pending_review",
                index=2,
                created=NOW - timedelta(minutes=5),
            ),
            _candidate(
                target_type="c7_layer4",
                state="pending_review",
                index=3,
                created=NOW - timedelta(hours=1),
            ),
            _candidate(
                target_type="pwc_combo",
                state="applied",
                index=4,
                created=NOW - timedelta(days=2),
                reviewed_at=NOW - timedelta(hours=1),
            ),
            # 窗外产出（31 天前已审）
            _candidate(
                target_type="pwc_combo",
                state="archived",
                index=5,
                created=NOW - timedelta(days=40),
                reviewed_at=NOW - timedelta(days=31),
            ),
            # 待办：未到期 / 已逾期未升级 / 已升级 / 窗内已决
            _todo(todo_type="ops_assist", due=NOW + timedelta(hours=10)),
            _todo(todo_type="ops_assist", due=NOW - timedelta(hours=1)),
            _todo(
                todo_type="law_review",
                status="escalated",
                due=NOW - timedelta(hours=20),
            ),
            _todo(
                todo_type="law_review",
                status="resolved",
                resolved_at=NOW - timedelta(hours=2),
            ),
        ])
        await session.commit()

    resp = await client.get(
        "/api/admin/dashboards/review-workload",
        params={"actor_id": PLATFORM_ADMIN["id"], "roles": PLATFORM_ADMIN["roles"]},
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()

    backlog = report["backlog"]
    cand = {row["target_type"]: row for row in backlog["candidates"]}
    assert cand["pwc_combo"]["pending"] == 2
    assert cand["pwc_combo"]["oldest_wait_seconds"] >= 7000
    assert cand["c7_layer4"]["pending"] == 1

    todos = {row["todo_type"]: row for row in backlog["todos"]}
    assert todos["ops_assist"] == {"todo_type": "ops_assist", "open": 1, "overdue": 1, "escalated": 0}
    assert todos["law_review"] == {"todo_type": "law_review", "open": 0, "overdue": 0, "escalated": 1}
    assert backlog["totals"] == {
        "pending_candidates": 3,
        "open_todos": 1,
        "overdue_todos": 1,
        "escalated_todos": 1,
    }

    decided = {row["state"]: row["count"] for row in report["window_output"]["candidates_decided"]}
    assert decided == {"applied": 1}
    resolved = {
        row["todo_type"]: row["count"]
        for row in report["window_output"]["todos_resolved"]
    }
    assert resolved == {"law_review": 1}
    assert report["snapshot_at"].endswith("+00:00")


async def test_review_workload_empty_store_returns_zeroed_snapshot(
    client, session_factory
):
    resp = await client.get(
        "/api/admin/dashboards/review-workload",
        params=[
            ("actor_id", PLATFORM_ADMIN["id"]),
            ("roles", PLATFORM_ADMIN["roles"][0]),
            ("date_from", date(2026, 9, 1).isoformat()),
            ("date_to", date(2026, 9, 10).isoformat()),
        ],
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["backlog"]["candidates"] == []
    assert report["backlog"]["todos"] == []
    assert report["backlog"]["totals"] == {
        "pending_candidates": 0,
        "open_todos": 0,
        "overdue_todos": 0,
        "escalated_todos": 0,
    }
    assert report["window_output"] == {"candidates_decided": [], "todos_resolved": []}


async def test_review_workload_forbidden_for_non_admin(client):
    resp = await client.get(
        "/api/admin/dashboards/review-workload",
        params={"actor_id": OPERATIONS["id"], "roles": OPERATIONS["roles"]},
    )
    assert resp.status_code == 403
