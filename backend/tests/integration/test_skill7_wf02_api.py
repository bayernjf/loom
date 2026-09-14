"""skill7 通道 WF-02 字段池替换切片集成测试（Q78，M10 WF 替换切片 1/3）。

DIM-MERGE 投递整方案单候选（target_type=field_plan）→ pending_review →
product_reviewer confirmed/modified/rejected → 适配器复用 fieldpool.submit_plan，
PT-FP-PLAN/Q8/Q9/Q10/Q12 全在既有服务内执行，落 pending_gate 走 WF-02 HumanGate。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import (
    ProductIntakeApplication,
    ProductSpace,
)

OPS = {"id": "ops-1", "roles": ["operations"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
NOBODY = {"id": "nobody-1", "roles": []}

ROUTES = [
    ("user_input", "用户输入", 1),
    ("common_inspiration", "通用灵感库", 2),
    ("product_inspiration", "产品灵感库", 3),
    ("category_template", "类目模板", 4),
    ("g2_frequent", "G2 高频", 5),
    ("compliance_risk", "合规风险面", 6),
]


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
                FPSourceRoute(route=route, name=name, sort_order=order)
                for route, name, order in ROUTES
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_ps(session_factory, *, industry="general", tenant="t1"):
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id=tenant, status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id=tenant,
            intake_id=intake.intake_id,
            industry_tag=industry,
            profile_snapshot={"f_a": "x"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


def _dim(i, **kw):
    base = {
        "field_name": f"维度{i}",
        "role": "product_attribute",
        "source_route": "user_input",
        "confidence": 0.9,
        "source_ref": f"ref-{i}",
    }
    base.update(kw)
    return base


def _plan(**kw):
    payload = {
        "dimensions": [_dim(1), _dim(2), _dim(3)],
        "target_atom_min": 15,
        "target_atom_max": 30,
    }
    payload.update(kw)
    return payload


def _deliver_body(ps_id, *, target_type="field_plan", payload=None, **extra):
    body = {
        "skill_id": "DIM-MERGE",
        "product_space_id": ps_id,
        "confidence": 0.8,
        "candidates": [
            {"target_type": target_type, "payload": payload or _plan()}
        ],
        "actor": OPS,
    }
    body.update(extra)
    return body


# ---------- 投递闸与 WF 声明对齐（Q78） ----------

async def test_deliver_requires_operations_and_validates(client, session_factory):
    ps_id = await _make_ps(session_factory)
    # 角色闸先于一切。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body("ps-nope", actor=NOBODY)
    )
    assert r.status_code == 403
    # operations 打不存在 PS → 404。
    r = await client.post("/api/skill-runs", json=_deliver_body("ps-nope"))
    assert r.status_code == 404
    # 未注册 Skill → 422。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(ps_id, skill_id="NO-SUCH")
    )
    assert r.status_code == 422
    # payload 不符 PlanSubmitRequest 契约（dimensions 空）→ 422。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(ps_id, payload=_plan(dimensions=[]))
    )
    assert r.status_code == 422
    # target_type 与 WF 声明不一致 → 422。
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(
            ps_id,
            target_type="pwc_combo",
            payload={"combos": []},
        ),
    )
    assert r.status_code == 422
    # field_plan 必须整方案单候选：两条 → 422。
    two = _deliver_body(ps_id)
    two["candidates"].append(two["candidates"][0])
    r = await client.post("/api/skill-runs", json=two)
    assert r.status_code == 422
    # 非候选产出步骤（FIELDPOOL-PLAN）带候选投递 → 422。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(ps_id, skill_id="FIELDPOOL-PLAN")
    )
    assert r.status_code == 422


async def test_valid_delivery_lands_pending_candidate(client, session_factory):
    ps_id = await _make_ps(session_factory)
    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id))
    assert r.status_code == 200, r.text
    assert r.json()["run"]["wf_id"] == "WF-02"
    candidate_id = r.json()["candidate_ids"][0]
    cands = await client.get(
        f"/api/skill-candidates?product_space_id={ps_id}&state=pending_review"
    )
    assert [c["candidate_id"] for c in cands.json()["candidates"]] == [candidate_id]
    # 投递不写 FieldPool：候选未裁前无池。
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    assert pool.status_code == 404


# ---------- confirmed：适配器落 pending_gate，再过 WF-02 Gate ----------

async def test_confirm_applies_field_plan_via_submit(client, session_factory):
    ps_id = await _make_ps(session_factory)
    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id))
    candidate_id = r.json()["candidate_ids"][0]

    # 裁决角色 = WF-02 skill7 插槽 product_reviewer；operations 不行。
    forb = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": OPS},
    )
    assert forb.status_code == 403

    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert ok.status_code == 200, ok.text
    view = ok.json()
    assert view["state"] == "applied"
    assert len(view["applied_refs"]) == 1

    # 适配器复用 submit_plan：池落 pending_gate（未绕 WF-02 HumanGate）。
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    assert pool.status_code == 200, pool.text
    body = pool.json()
    assert body["pool_id"] == view["applied_refs"][0]
    assert body["gate"] == "pending_gate"
    assert len(body["dimensions"]) == 3

    # 既有 Gate 照常可裁（approved 后链路继续）。
    gate = await client.post(
        f"/api/field-pools/{body['pool_id']}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text


async def test_reject_archives_without_pool(client, session_factory):
    ps_id = await _make_ps(session_factory)
    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id))
    candidate_id = r.json()["candidate_ids"][0]
    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "rejected", "reason": "维度方向不对", "actor": REVIEWER},
    )
    assert ok.status_code == 200
    assert ok.json()["state"] == "archived"
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    assert pool.status_code == 404


async def test_modified_replaces_payload_and_marks_human_modified(
    client, session_factory
):
    ps_id = await _make_ps(session_factory)
    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id))
    candidate_id = r.json()["candidate_ids"][0]

    # 改单 payload 仍过 PlanSubmitRequest 结构校验：confidence 越界 → 422。
    bad = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={
            "decision": "modified",
            "payload": _plan(dimensions=[_dim(1, confidence=1.5)]),
            "actor": REVIEWER,
        },
    )
    assert bad.status_code == 422

    replacement = _plan(
        dimensions=[_dim(1, confidence=0.95), _dim(2), _dim(3)],
        target_atom_min=18,
    )
    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "modified", "payload": replacement, "actor": REVIEWER},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["human_modified"] is True
    assert ok.json()["payload"]["target_atom_min"] == 18
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    assert pool.status_code == 200
    assert pool.json()["target_atom_min"] == 18


async def test_apply_failure_keeps_candidate_pending(client, session_factory):
    # 已有未被驳回的池：适配器 submit_plan 抛 GateNotAllowed → 409，
    # 事务回滚，候选留在 pending_review 可重裁。
    ps_id = await _make_ps(session_factory)
    seed = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools",
        json={"dimensions": [_dim(1), _dim(2), _dim(3)], "actor": OPS},
    )
    assert seed.status_code == 200, seed.text

    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id))
    assert r.status_code == 200, r.text
    candidate_id = r.json()["candidate_ids"][0]
    bad = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert bad.status_code == 409
    cands = await client.get(
        f"/api/skill-candidates?product_space_id={ps_id}&state=pending_review"
    )
    assert [c["candidate_id"] for c in cands.json()["candidates"]] == [candidate_id]
