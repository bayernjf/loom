"""候选审核 SLA 待办挂接集成测试（Q70②/Q94）。

投递（/api/skill-runs，人工与 llm_auto 同一通道）即按候选 target_type 的
配置时限建 ops_todo；裁决（逐条/工作台批量）即 resolve；到期经 Q49 引擎
置 escalated 且审计 skill7.review_sla_escalated，升级不阻断裁决收口。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.sla.engine import escalate_due_todos
from app.main import app
from app.product.fieldpool.models import FPSourceRoute
from app.product.modeling.models import (
    C1IndustryThreshold,
    C1SignalWeight,
    OpsTodo,
)
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import (
    ProductIntakeApplication,
    ProductSpace,
)

OPS = {"id": "ops-1", "roles": ["operations"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}


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
            C1SignalWeight(signal="name", signal_name="产品名", enabled=True, weight=0.50),
            C1SignalWeight(signal="brief", signal_name="简介", enabled=True, weight=0.33),
            C1SignalWeight(signal="sellpoint", signal_name="卖点", enabled=True, weight=0.17),
            C1IndustryThreshold(
                industry="general", keywords=[], threshold=0.85,
                sensitive=False, is_default=True,
            ),
            FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
            FPSourceRoute(route="compliance_risk", name="合规风险面", sort_order=2),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------- 构造 ----------


async def _make_intake(client) -> str:
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "合成面霜", "f_brief": "保湿"}},
    )
    assert r.status_code == 201, r.text
    intake_id = r.json()["intake_id"]
    r = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "submit", "actor": {"id": "cust-1", "roles": ["customer"]}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == sm.AI_RECOGNIZING
    return intake_id


async def _make_ps(session_factory, *, industry="general") -> str:
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id="t1", status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id="t1",
            intake_id=intake.intake_id,
            industry_tag=industry,
            profile_snapshot={"f_a": "x"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


def _recog_payload():
    return {
        "signals": {"name": 0.95, "brief": 0.95, "sellpoint": 0.9},
        "candidates": [
            {"category_id": "synth-c1", "conf": 0.95},
            {"category_id": "synth-c2", "conf": 0.5},
        ],
    }


async def _deliver_c1(client, intake_id):
    return await client.post(
        "/api/skill-runs",
        json={
            "skill_id": "CAT-RECOG",
            "intake_id": intake_id,
            "confidence": 0.9,
            "candidates": [
                {"target_type": "c1_recognition", "payload": _recog_payload()}
            ],
            "actor": OPS,
        },
    )


def _atom_items(*contents):
    return [
        {
            "content": content,
            "dimension_id": f"d{i}",
            "ai_risk": "low",
            "evidence": f"依据 {content}",
        }
        for i, content in enumerate(contents)
    ]


async def _deliver_atom(client, ps_id, items=None, *, confidence=0.5):
    return await client.post(
        "/api/skill-runs",
        json={
            "skill_id": "CONFLICT-PRECHECK",
            "wf_id": "WF-03",
            "product_space_id": ps_id,
            "confidence": confidence,
            "candidates": [
                {"target_type": "atom_batch", "payload": {"items": items or _atom_items("温和")}}
            ],
            "actor": OPS,
        },
    )


async def _open_todos(session_factory, candidate_id=None):
    async with session_factory() as session:
        stmt = select(OpsTodo).where(OpsTodo.entity_type == "skill_candidate")
        if candidate_id is not None:
            stmt = stmt.where(OpsTodo.entity_id == candidate_id)
        return list((await session.scalars(stmt)).all())


# ---------- 1. 投递建待办：粒度/角色/时限/链接 ----------


async def test_delivery_opens_one_review_todo_per_candidate_with_wf_role(
    client, session_factory
):
    intake_id = await _make_intake(client)
    r = await _deliver_c1(client, intake_id)
    assert r.status_code == 200, r.text
    c1_id = r.json()["candidate_ids"][0]

    ps_id = await _make_ps(session_factory)
    r = await _deliver_atom(client, ps_id)
    assert r.status_code == 200, r.text
    atom_id = r.json()["candidate_ids"][0]

    todos = {t.entity_id: t for t in await _open_todos(session_factory)}
    assert set(todos) == {c1_id, atom_id}

    c1_todo = todos[c1_id]
    assert c1_todo.todo_type == "review_c1_recognition"
    assert c1_todo.assignee_role == "operations"  # WF-01 Gate
    assert c1_todo.status == "open"
    assert c1_todo.detail["target_type"] == "c1_recognition"
    assert c1_todo.detail["candidate_index"] == 0
    assert c1_todo.detail["run_id"]

    atom_todo = todos[atom_id]
    assert atom_todo.todo_type == "review_atom_batch"
    assert atom_todo.assignee_role == "product_reviewer"  # WF-03 Gate

    # 默认 72h（原文未给，种子 72 待补）；窗口放宽到秒级计时误差。
    now = datetime.now(UTC)
    for todo in (c1_todo, atom_todo):
        due = todo.due_at.replace(tzinfo=UTC) if todo.due_at.tzinfo is None else todo.due_at
        delta = due - now
        assert timedelta(hours=71, minutes=59) < delta < timedelta(hours=72, minutes=1)


async def test_multi_candidate_delivery_opens_multiple_todos(client, session_factory):
    # WF-04 PWC-BUILDER 允许一次多候选：每候选各一条。
    ps_id = await _make_ps(session_factory)
    r = await client.post(
        "/api/skill-runs",
        json={
            "skill_id": "PWC-BUILDER",
            "wf_id": "WF-04",
            "product_space_id": ps_id,
            "confidence": 0.6,
            "candidates": [
                {
                    "target_type": "pwc_combo",
                    "payload": {"combos": [{"atom_ids": ["a1", "a2"]}]},
                },
                {
                    "target_type": "pwc_combo",
                    "payload": {"combos": [{"atom_ids": ["a3", "a4"]}]},
                },
            ],
            "actor": OPS,
        },
    )
    assert r.status_code == 200, r.text
    ids = r.json()["candidate_ids"]
    assert len(ids) == 2
    todos = await _open_todos(session_factory)
    assert len(todos) == 2
    assert {t.entity_id for t in todos} == set(ids)
    assert all(t.todo_type == "review_pwc_combo" for t in todos)
    assert {t.detail["candidate_index"] for t in todos} == {0, 1}


# ---------- 2/3. 裁决即 resolve ----------


async def test_reject_resolves_todo_archived(client, session_factory):
    intake_id = await _make_intake(client)
    candidate_id = (await _deliver_c1(client, intake_id)).json()["candidate_ids"][0]

    r = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "rejected", "reason": "不采纳", "actor": OPS},
    )
    assert r.status_code == 200, r.text

    todo = (await _open_todos(session_factory, candidate_id))[0]
    # 行保留（审计链），状态 resolved；open 待办池为空。
    assert todo.status == "resolved"
    assert todo.resolution == "archived"
    assert todo.resolved_at is not None


async def test_apply_resolves_todo_applied(client, session_factory):
    ps_id = await _make_ps(session_factory)
    body = {
        "dimensions": [
            {
                "field_name": f"维度{i}",
                "role": "product_attribute",
                "source_route": "user_input",
                "confidence": 0.9,
                "source_ref": f"ref-{i}",
            }
            for i in (1, 2, 3)
        ],
        "actor": OPS,
        "target_atom_min": 15,
        "target_atom_max": 30,
    }
    pool_id = (
        await client.post(f"/api/product-spaces/{ps_id}/field-pools", json=body)
    ).json()["pool_id"]
    gate = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text
    pool = (await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")).json()
    d1 = pool["dimensions"][0]["dimension_id"]

    r = await _deliver_atom(client, ps_id, _atom_items_for(d1))
    candidate_id = r.json()["candidate_ids"][0]
    r = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert r.status_code == 200, r.text

    todo = (await _open_todos(session_factory, candidate_id))[0]
    assert todo.status == "resolved"
    assert todo.resolution == "applied"


def _atom_items_for(dim):
    return [{"content": "温和不刺激", "dimension_id": dim, "ai_risk": "low",
             "evidence": "依据 温和不刺激"}]


# ---------- 4. 到期升级 + 升级后裁决仍可收口 ----------


async def test_escalation_marks_due_todos_and_decision_still_resolves(
    client, session_factory
):
    intake_id = await _make_intake(client)
    candidate_id = (await _deliver_c1(client, intake_id)).json()["candidate_ids"][0]
    todo = (await _open_todos(session_factory, candidate_id))[0]

    # 人工置过期（不等待 72h），跑 Q49 引擎。
    async with session_factory() as session:
        row = await session.get(OpsTodo, todo.todo_id)
        row.due_at = datetime.now(UTC) - timedelta(minutes=1)
        escalated = await escalate_due_todos(session)
        await session.commit()
    assert len(escalated) == 1

    async with session_factory() as session:
        row = await session.get(OpsTodo, todo.todo_id)
        assert row.status == "escalated"
        assert row.escalated_at is not None
        audit = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "skill7.review_sla_escalated",
                    AuditLog.entity_id == todo.todo_id,
                )
            )
        ).all()
        assert len(audit) == 1

    # 升级不阻断裁决：reject 后待办收口 resolved。
    r = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "rejected", "actor": OPS},
    )
    assert r.status_code == 200, r.text
    todo = (await _open_todos(session_factory, candidate_id))[0]
    assert todo.status == "resolved"
    assert todo.resolution == "archived"


# ---------- 5. 工作台批量通过同步收口全部待办 ----------


async def test_batch_approve_resolves_all_review_todos(client, session_factory):
    ps_id = await _make_ps(session_factory)
    body = {
        "dimensions": [
            {
                "field_name": f"维度{i}",
                "role": "product_attribute",
                "source_route": "user_input",
                "confidence": 0.9,
                "source_ref": f"ref-{i}",
            }
            for i in (1, 2, 3)
        ],
        "actor": OPS,
        "target_atom_min": 15,
        "target_atom_max": 30,
    }
    pool_id = (
        await client.post(f"/api/product-spaces/{ps_id}/field-pools", json=body)
    ).json()["pool_id"]
    gate = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text
    pool = (await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")).json()
    d1, d2 = (d["dimension_id"] for d in pool["dimensions"][:2])

    first = await client.post(
        "/api/skill-runs",
        json={
            "skill_id": "CONFLICT-PRECHECK",
            "wf_id": "WF-03",
            "product_space_id": ps_id,
            "confidence": 0.91,
            "candidates": [
                {"target_type": "atom_batch",
                 "payload": {"items": [
                     {"content": "温和", "dimension_id": d1, "ai_risk": "low",
                      "evidence": "依据 温和"}
                 ]}}
            ],
            "actor": OPS,
        },
    )
    second = await client.post(
        "/api/skill-runs",
        json={
            "skill_id": "CONFLICT-PRECHECK",
            "wf_id": "WF-03",
            "product_space_id": ps_id,
            "confidence": 0.93,
            "candidates": [
                {"target_type": "atom_batch",
                 "payload": {"items": [
                     {"content": "清爽", "dimension_id": d2, "ai_risk": "low",
                      "evidence": "依据 清爽"}
                 ]}}
            ],
            "actor": OPS,
        },
    )
    ids = [first.json()["candidate_ids"][0], second.json()["candidate_ids"][0]]

    r = await client.post(
        "/api/review-workbench/batch-approve",
        json={"candidate_ids": ids, "actor": REVIEWER},
    )
    assert r.status_code == 200, r.text

    todos = await _open_todos(session_factory)
    assert len(todos) == 2
    assert all(t.status == "resolved" and t.resolution == "applied" for t in todos)
    assert {t.entity_id for t in todos} == set(ids)


# ---------- 6. 驾驶舱积压自动出现新 todo_type ----------


async def test_dashboard_backlog_groups_review_todo_types(client, session_factory):
    ps_id = await _make_ps(session_factory)
    r = await _deliver_atom(client, ps_id)
    candidate_id = r.json()["candidate_ids"][0]
    todo = (await _open_todos(session_factory, candidate_id))[0]

    # 置过期但不跑升级 → open 且 overdue。
    async with session_factory() as session:
        row = await session.get(OpsTodo, todo.todo_id)
        row.due_at = datetime.now(UTC) - timedelta(minutes=5)
        await session.commit()

    r = await client.get(
        "/api/admin/dashboards/review-workload",
        params=[("actor_id", ADMIN["id"]), ("roles", "platform_admin")],
    )
    assert r.status_code == 200, r.text
    by_type = {
        row["todo_type"]: row
        for row in r.json()["backlog"]["todos"]
    }
    assert by_type["review_atom_batch"]["open"] == 0
    assert by_type["review_atom_batch"]["overdue"] == 1
    assert by_type["review_atom_batch"]["escalated"] == 0
