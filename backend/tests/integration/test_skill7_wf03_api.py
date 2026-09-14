"""skill7 通道 WF-03 字段下原子替换切片集成测试（Q80，M10 WF 替换切片 3/3）。

CONFLICT-PRECHECK 投递整批单候选（target_type=atom_batch）→ pending_review →
product_reviewer confirmed/modified/rejected → 适配器复用 atom.submit_batch
（强制 source=ai），Q14/Q15/同批去重/维度归属/Q17/line 840/PT-ATOM-EXP
全部在既有服务内执行；skill7 只管整批准入，入库后逐条 approveAtomGuard 不变。
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
                FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
                FPSourceRoute(
                    route="compliance_risk", name="合规风险面", sort_order=2
                ),
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


async def _approved_pool(client, ps_id, *, target_min=15, target_max=30):
    body = {
        "dimensions": [_dim(1), _dim(2), _dim(3)],
        "actor": OPS,
        "target_atom_min": target_min,
        "target_atom_max": target_max,
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


def _items(d1, d2):
    return [
        {"content": "温和不刺激", "dimension_id": d1, "ai_risk": "low", "evidence": "评论依据 1"},
        {"content": "每天使用两次", "dimension_id": d2, "ai_risk": "low", "evidence": "评论依据 2"},
    ]


def _deliver_body(ps_id, *, payload=None, **extra):
    pool_dims = extra.pop("_pool_dims", None)
    items = payload
    if items is None:
        assert pool_dims is not None
        items = {"items": _items(pool_dims[0], pool_dims[1])}
    body = {
        "skill_id": "CONFLICT-PRECHECK",
        "wf_id": "WF-03",
        "product_space_id": ps_id,
        "confidence": 0.8,
        "candidates": [{"target_type": "atom_batch", "payload": items}],
        "actor": OPS,
    }
    body.update(extra)
    return body


# ---------- 投递闸与 WF 声明对齐（Q80） ----------

async def test_deliver_requires_operations_and_validates(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    dims = [d["dimension_id"] for d in pool["dimensions"]]

    # 角色闸先于一切。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body("ps-nope", _pool_dims=dims, actor=NOBODY)
    )
    assert r.status_code == 403
    # operations 打不存在 PS → 404。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body("ps-nope", _pool_dims=dims)
    )
    assert r.status_code == 404
    # 非候选产出步骤（ATOM-EXPAND）带候选投递 → 422。
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(ps_id, _pool_dims=dims, skill_id="ATOM-EXPAND"),
    )
    assert r.status_code == 422
    # payload 不符 BatchSubmitRequest 契约（items 空）→ 422。
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(ps_id, payload={"items": []}),
    )
    assert r.status_code == 422
    # target_type 与 WF 声明不一致 → 422。
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(
            ps_id,
            payload={"combos": []},
            candidates=[
                {"target_type": "pwc_combo", "payload": {"combos": []}}
            ],
        ),
    )
    assert r.status_code == 422
    # atom_batch 必须整批单候选：两条 → 422。
    two = _deliver_body(ps_id, _pool_dims=dims)
    two["candidates"].append(two["candidates"][0])
    r = await client.post("/api/skill-runs", json=two)
    assert r.status_code == 422
    # PS 锚点专属：带 intake_id → 422。
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(
            ps_id, _pool_dims=dims, product_space_id=None, intake_id="intake-x"
        ),
    )
    assert r.status_code == 422


async def test_valid_delivery_lands_pending_without_batch(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    dims = [d["dimension_id"] for d in pool["dimensions"]]

    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id, _pool_dims=dims))
    assert r.status_code == 200, r.text
    assert r.json()["run"]["wf_id"] == "WF-03"
    candidate_id = r.json()["candidate_ids"][0]
    cands = await client.get(
        f"/api/skill-candidates?product_space_id={ps_id}&state=pending_review"
    )
    assert [c["candidate_id"] for c in cands.json()["candidates"]] == [candidate_id]
    # 投递不写原子批次：候选未裁前无 AtomBatch/AtomCandidate。
    atoms = await client.get(f"/api/product-spaces/{ps_id}/atom-candidates")
    assert atoms.json() == []


# ---------- confirmed：适配器落批次，逐条 Gate 原样保留 ----------

async def test_confirm_applies_batch_via_submit(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1, d2 = (d["dimension_id"] for d in pool["dimensions"][:2])
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(ps_id, _pool_dims=[d1, d2])
    )
    candidate_id = r.json()["candidate_ids"][0]

    # 裁决角色 = WF-03 skill7 插槽 product_reviewer；operations 不行。
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
    assert len(view["applied_refs"]) == 1  # AtomBatch id

    # 适配器复用 submit_batch：两条 AtomCandidate 落 pending_review（带证据）。
    rows = await client.get(f"/api/product-spaces/{ps_id}/atom-candidates")
    items = rows.json()
    assert len(items) == 2
    assert {c["status"] for c in items} == {"pending_review"}
    assert {c["risk_source"] for c in items} == {"ai"}

    # 下游 approveAtomGuard 逐条 Gate 不绕：product_reviewer 可正式化一条。
    approved = await client.post(
        f"/api/atom-candidates/{items[0]['candidate_id']}/approve",
        json={"actor": REVIEWER},
    )
    assert approved.status_code == 200, approved.text
    atoms = await client.get(f"/api/product-spaces/{ps_id}/atoms")
    assert len(atoms.json()) == 1


async def test_reject_archives_without_batch(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    dims = [d["dimension_id"] for d in pool["dimensions"]]
    r = await client.post("/api/skill-runs", json=_deliver_body(ps_id, _pool_dims=dims))
    candidate_id = r.json()["candidate_ids"][0]
    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "rejected", "reason": "词条方向不对", "actor": REVIEWER},
    )
    assert ok.status_code == 200
    assert ok.json()["state"] == "archived"
    rows = await client.get(f"/api/product-spaces/{ps_id}/atom-candidates")
    assert rows.json() == []


async def test_modified_replaces_payload_and_marks_human_modified(
    client, session_factory
):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1, d2, d3 = (d["dimension_id"] for d in pool["dimensions"])
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(ps_id, _pool_dims=[d1, d2])
    )
    candidate_id = r.json()["candidate_ids"][0]

    # 改单 payload 仍过 BatchSubmitRequest 结构校验：坏维度引用在适配器侧 422。
    bad = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={
            "decision": "modified",
            "payload": {"items": [{"content": "x", "dimension_id": "wrong-dim"}]},
            "actor": REVIEWER,
        },
    )
    assert bad.status_code == 422

    replacement = {
        "items": [
            {"content": "改后词条", "dimension_id": d3, "ai_risk": "low", "evidence": "e3"}
        ]
    }
    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "modified", "payload": replacement, "actor": REVIEWER},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["human_modified"] is True
    rows = await client.get(f"/api/product-spaces/{ps_id}/atom-candidates")
    assert [c["content"] for c in rows.json()] == ["改后词条"]


async def test_pool_not_approved_confirm_409_keeps_pending(client, session_factory):
    # 有 FieldPool 但未过 WF-02 Gate：适配器 submit_batch 抛 PoolNotApproved → 409，
    # 事务回滚，候选留 pending_review 可重裁。
    ps_id = await _make_ps(session_factory)
    seeded = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools",
        json={"dimensions": [_dim(1), _dim(2), _dim(3)], "actor": OPS},
    )
    assert seeded.status_code == 200, seeded.text  # 落 pending_gate，未 approve
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(
            ps_id,
            payload={"items": [{"content": "词条", "dimension_id": "dim-x", "evidence": "e"}]},
        ),
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


async def test_target_reached_confirm_409_keeps_pending_q15(client, session_factory):
    # Q15：已通过正式原子达 target_atom_max → AI 批次 409 停拓，候选留 pending。
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id, target_min=1, target_max=1)
    d1, d2 = (d["dimension_id"] for d in pool["dimensions"][:2])

    seeded = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches",
        json={
            "items": [{"content": "既有词条", "dimension_id": d1, "ai_risk": "low", "evidence": "e"}],
            "actor": OPS,
        },
    )
    assert seeded.status_code == 200, seeded.text
    cid = seeded.json()["candidates"][0]["candidate_id"]
    approved = await client.post(
        f"/api/atom-candidates/{cid}/approve", json={"actor": REVIEWER}
    )
    assert approved.status_code == 200

    r = await client.post(
        "/api/skill-runs", json=_deliver_body(ps_id, _pool_dims=[d1, d2])
    )
    candidate_id = r.json()["candidate_ids"][0]
    blocked = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert blocked.status_code == 409
    cands = await client.get(
        f"/api/skill-candidates?product_space_id={ps_id}&state=pending_review"
    )
    assert [c["candidate_id"] for c in cands.json()["candidates"]] == [candidate_id]


async def test_missing_evidence_item_lands_pending_evidence(client, session_factory):
    # PT-ATOM-EXP-V1.3：空证据降级由既有 submit_batch 机械执行，准入不改变它。
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(
            ps_id, payload={"items": [{"content": "无证据词条", "dimension_id": d1}]}
        ),
    )
    candidate_id = r.json()["candidate_ids"][0]
    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert ok.status_code == 200, ok.text
    rows = await client.get(f"/api/product-spaces/{ps_id}/atom-candidates")
    item = rows.json()[0]
    assert item["status"] == "pending_evidence"
    assert item["evidence_due_at"] is not None
