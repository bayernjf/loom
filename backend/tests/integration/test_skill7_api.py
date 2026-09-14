"""skill7 AI 候选通道集成测试（M10 切片 e，Q76）。

通道核心 + WF-04 试点：外部投递（operations）→ pending_review →
product_reviewer confirmed/modified/rejected → 复用 pwc/funnel 适配落库；
Q71 补货只记 requested run、防抖不造候选。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import (
    G2Field,
    ProductIntakeApplication,
    ProductSpace,
)

OPS = {"id": "ops-1", "roles": ["operations"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
NOBODY = {"id": "nobody-1", "roles": []}


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
                G2Field(fid="f_a", cat="common", field_name="字段A"),
                G2Field(fid="f_b", cat="selling", field_name="字段B"),
                FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
                FPSourceRoute(route="compliance_risk", name="合规风险面", sort_order=2),
            ]
            + [ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


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


async def _approved_pool(client, ps_id):
    body = {
        "dimensions": [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)],
        "actor": OPS,
    }
    resp = await client.post(f"/api/product-spaces/{ps_id}/field-pools", json=body)
    assert resp.status_code == 200, resp.text
    pool_id = resp.json()["pool_id"]
    gate = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    return pool.json()


async def _approved_atoms(client, ps_id):
    pool = await _approved_pool(client, ps_id)
    dim_ids = [d["dimension_id"] for d in pool["dimensions"][:2]]
    items = [
        {
            "content": f"原子{i}",
            "dimension_id": dim_ids[i],
            "ai_risk": "low",
            "evidence": "客服语料",
        }
        for i in range(2)
    ]
    resp = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches", json={"items": items, "actor": OPS}
    )
    assert resp.status_code == 200, resp.text
    for c in resp.json()["candidates"]:
        ok = await client.post(
            f"/api/atom-candidates/{c['candidate_id']}/approve", json={"actor": REVIEWER}
        )
        assert ok.status_code == 200, ok.text
    atoms = (await client.get(f"/api/product-spaces/{ps_id}/atoms")).json()
    return [a["atom_id"] for a in atoms]


def _combo(atom_ids, **kw):
    base = {"atom_ids": atom_ids, "logic_score": 0.8, "fit_score": 0.6}
    base.update(kw)
    return base


async def _seeded_ps(client, session_factory):
    ps_id = await _make_ps(session_factory)
    atoms = await _approved_atoms(client, ps_id)
    return ps_id, atoms


def _deliver_body(ps_id, atoms, **extra):
    body = {
        "skill_id": "PWC-BUILDER",
        "product_space_id": ps_id,
        "input_tokens": 120,
        "output_tokens": 80,
        "confidence": 0.77,
        "candidates": [
            {"target_type": "pwc_combo", "payload": {"combos": [_combo(atoms)]}}
        ],
        "actor": OPS,
    }
    body.update(extra)
    return body


# ---------- 投递闸与契约 ----------

async def test_deliver_requires_operations_and_validates(client, session_factory):
    ps_id = await _make_ps(session_factory)
    # 角色闸先于一切：错角色打不存在 PS 仍是 403。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body("ps-nope", ["a", "b"], actor=NOBODY)
    )
    assert r.status_code == 403
    # operations 打不存在 PS → 404。
    r = await client.post("/api/skill-runs", json=_deliver_body("ps-nope", ["a", "b"]))
    assert r.status_code == 404
    # 未注册 Skill → 422。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(ps_id, ["a", "b"], skill_id="NO-SUCH")
    )
    assert r.status_code == 422
    # payload 不符 ComboItem 契约（单原子）→ 422。
    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id, ["only-one"]))
    assert r.status_code == 422


# ---------- 候选状态机：confirmed / rejected / modified ----------

async def test_deliver_confirm_applies_via_funnel(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id, atoms))
    assert r.status_code == 200, r.text
    run_id = r.json()["run"]["run_id"]
    candidate_id = r.json()["candidate_ids"][0]
    assert r.json()["run"]["status"] == "succeeded"

    listed = await client.get(f"/api/skill-runs?product_space_id={ps_id}")
    assert [x["run_id"] for x in listed.json()["runs"]] == [run_id]

    cands = await client.get(
        f"/api/skill-candidates?product_space_id={ps_id}&state=pending_review"
    )
    assert len(cands.json()["candidates"]) == 1

    # 非 product_reviewer 不能裁决（403，先于候选存在性）。
    forb = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": OPS},
    )
    assert forb.status_code == 403
    miss = await client.post(
        "/api/skill-candidates/nope/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert miss.status_code == 404

    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert ok.status_code == 200, ok.text
    view = ok.json()
    assert view["state"] == "applied"
    assert len(view["applied_refs"]) == 1

    # 适配器走的是既有漏斗：组合已落 PWC 且沿用其 Gate 流程。
    pwcs = (await client.get(f"/api/product-spaces/{ps_id}/pwcs")).json()
    assert {p["pwc_id"] for p in pwcs} == set(view["applied_refs"])

    # 已裁决候选不可再裁决。
    again = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "rejected", "actor": REVIEWER},
    )
    assert again.status_code == 409


async def test_reject_archives_without_pwc(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id, atoms))
    candidate_id = r.json()["candidate_ids"][0]
    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "rejected", "reason": "场景不搭", "actor": REVIEWER},
    )
    assert ok.status_code == 200
    assert ok.json()["state"] == "archived"
    pwcs = (await client.get(f"/api/product-spaces/{ps_id}/pwcs")).json()
    assert pwcs == []


async def test_modified_requires_payload_and_marks_human_modified(
    client, session_factory
):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id, atoms))
    candidate_id = r.json()["candidate_ids"][0]
    no_payload = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "modified", "actor": REVIEWER},
    )
    assert no_payload.status_code == 422

    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={
            "decision": "modified",
            "payload": {"combos": [_combo(atoms, logic_score=0.9)]},
            "actor": REVIEWER,
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["human_modified"] is True
    assert ok.json()["state"] == "applied"


async def test_apply_failure_keeps_candidate_pending(client, session_factory):
    # 无 approved 池：confirmed 时漏斗 409，候选留在 pending_review 可重裁。
    ps_id = await _make_ps(session_factory)
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(ps_id, ["atom-x", "atom-y"])
    )
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


# ---------- Q71 critical→target 补货：requested run + 防抖（Q76-4） ----------

async def test_consume_below_critical_requests_restock_with_debounce(
    client, session_factory
):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    # 既有通道造 1 个待用 PWC（ready=1 < critical 50）。
    funnel = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/funnel",
        json={"combos": [_combo(atoms)], "actor": OPS},
    )
    assert funnel.status_code == 200, funnel.text
    pwc_id = funnel.json()[0]["pwc_id"]
    gate = await client.post(
        f"/api/pwcs/{pwc_id}/gate", json={"decision": "approve", "actor": REVIEWER}
    )
    assert gate.status_code == 200, gate.text

    first = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "xhs", "account": "a1", "slot": "s1", "actor": OPS},
    )
    assert first.status_code == 200, first.text
    run_id = first.json()["restock_run_id"]
    assert run_id is not None

    run = await client.get(f"/api/skill-runs/{run_id}")
    assert run.json()["status"] == "requested"
    assert run.json()["source"] == "restock_auto"
    assert run.json()["skill_id"] == "PWC-BUILDER"
    # requested run 不产候选。
    cands = await client.get(f"/api/skill-candidates?product_space_id={ps_id}")
    assert cands.json()["candidates"] == []

    # 换发布三元组再消费（PWC 跨平台复用）：防抖窗口内不再造 requested run。
    second = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "dy", "account": "a2", "slot": "s2", "actor": OPS},
    )
    assert second.status_code == 200, second.text
    assert second.json()["restock_run_id"] is None
    runs = await client.get(
        f"/api/skill-runs?product_space_id={ps_id}&status=requested"
    )
    assert len(runs.json()["runs"]) == 1
