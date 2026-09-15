"""Q85 集成测试：WF-02 字段池方案（DIM-MERGE）第四站真 LLM 全链路。

形态与 Q82/Q83/Q84 同档：operations 显式端点 → 模型网关（synthetic 确定性
替身）→ 整方案单候选（field_plan，product_space 锚点）落 pending_review →
product_reviewer 裁决后适配器复用 fieldpool.submit_plan（PT-FP-PLAN/
Q8/Q9/Q10/Q11/Q12/Q15/line 14081 不绕）。create_all 不跑迁移种子，平台三行
由本文件 helper 自行插入；业务数据全部合成（16 §4）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.model_registry import drivers, synthetic
from app.core.model_registry.drivers import GenerationResult
from app.core.model_registry.models import (
    AIModel,
    AISceneRoute,
    SkillPrompt,
    SkillPromptVersion,
)
from app.core.model_registry.seeds import (
    DIM_MERGE_PROMPT_ID,
    DIM_MERGE_PROMPT_TEMPLATE,
    DIM_MERGE_PROMPT_VARIABLES,
    DIM_MERGE_PROMPT_VERSION,
    SCENE_DIM_MERGE,
    SYNTHETIC_MODEL_ID,
)
from app.core.skill7.models import SkillCandidate, SkillRun
from app.main import app
from app.product.fieldpool.models import FieldPool, FPSourceRoute
from app.product.product_intake.models import (
    G2Field,
    ProductIntakeApplication,
    ProductSpace,
)

OPS = {"id": "ops-1", "roles": ["operations"]}
PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


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
            AIModel(
                model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
                provider="synthetic", status="active",
            ),
            AISceneRoute(scene=SCENE_DIM_MERGE, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_DIM_MERGE, current_version=DIM_MERGE_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=DIM_MERGE_PROMPT_ID, skill_id=SCENE_DIM_MERGE,
                version=DIM_MERGE_PROMPT_VERSION, template=DIM_MERGE_PROMPT_TEMPLATE,
                variables={"vars": DIM_MERGE_PROMPT_VARIABLES},
            ),
            G2Field(fid="f_a", cat="common", field_name="字段A"),
            G2Field(fid="f_b", cat="selling", field_name="字段B"),
            FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
            FPSourceRoute(route="g2_frequent", name="G2高频", sort_order=2),
            FPSourceRoute(route="compliance_risk", name="合规风险面", sort_order=3),
            FPSourceRoute(route="disabled_route", name="停用路", enabled=False, sort_order=4),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _make_ps(session_factory, *, sensitive=False) -> str:
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id="t1", status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id="t1",
            intake_id=intake.intake_id,
            sensitive_industry=sensitive,
            industry_tag="medical" if sensitive else "general",
            profile_snapshot={"f_a": "合成面霜", "f_b": "保湿"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


def _plan_body(**kw):
    body = {"actor": OPS}
    body.update(kw)
    return body


async def _count(session_factory, model) -> int:
    async with session_factory() as session:
        return (await session.scalars(select(func.count()).select_from(model))).one()


def _dim(i, **kw):
    base = {
        "field_name": f"维度{i}",
        "role": "product_attribute",
        "source_route": "user_input",
        "confidence": 0.9,
        "source_ref": f"product_profile:k{i}",
    }
    base.update(kw)
    return base


# ---------- happy path → product_reviewer Gate → submit_plan pending_gate -------

async def test_llm_plan_happy_path_then_confirm_to_pending_gate(client, session_factory):
    ps_id = await _make_ps(session_factory)
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "llm_auto"
    assert body["model_id"] == SYNTHETIC_MODEL_ID
    assert body["input_tokens"] >= 1 and body["output_tokens"] >= 1
    assert body["candidates"] == [{
        "candidate_id": body["candidates"][0]["candidate_id"],
        "state": "pending_review",
        "target_type": "field_plan",
    }]
    cand_id = body["candidates"][0]["candidate_id"]

    async with session_factory() as session:
        run = await session.get(SkillRun, body["run_id"])
        assert run.source == "llm_auto" and run.model_id == SYNTHETIC_MODEL_ID
        assert run.input_cost is not None and run.output_cost is not None
        cand = await session.get(SkillCandidate, cand_id)
        assert cand.state == "pending_review"
        assert cand.payload["target_atom_min"] == 15
        assert cand.payload["target_atom_max"] == 30
        names = [d["field_name"] for d in cand.payload["dimensions"]]
        assert names == ["字段A", "字段B", "f_a"]
        assert all(d["source_ref"].strip() for d in cand.payload["dimensions"])
    assert await _count(session_factory, FieldPool) == 0  # 未裁前不落池

    # WF-02 skill7 插槽裁决角色 = product_reviewer；operations 不行。
    forb = await client.post(
        f"/api/skill-candidates/{cand_id}/decision",
        json={"decision": "confirmed", "actor": OPS},
    )
    assert forb.status_code == 403
    ok = await client.post(
        f"/api/skill-candidates/{cand_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["state"] == "applied"

    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    assert pool.status_code == 200, pool.text
    p = pool.json()
    assert p["gate"] == "pending_gate" and p["compliant"] is True
    assert p["violations"] == []
    assert len(p["dimensions"]) == 3
    gate = await client.post(
        f"/api/field-pools/{p['pool_id']}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text


async def test_llm_plan_sensitive_industry_includes_risk_control(client, session_factory):
    ps_id = await _make_ps(session_factory, sensitive=True)
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 201, r.text
    cand_id = r.json()["candidates"][0]["candidate_id"]
    async with session_factory() as session:
        cand = await session.get(SkillCandidate, cand_id)
        roles = [d["role"] for d in cand.payload["dimensions"]]
    assert "risk_control" in roles

    ok = await client.post(
        f"/api/skill-candidates/{cand_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert ok.status_code == 200, ok.text
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    assert pool.json()["compliant"] is True


async def test_llm_plan_echoes_trigger_target_atom_range(client, session_factory):
    ps_id = await _make_ps(session_factory)
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan",
        json=_plan_body(target_atom_min=12, target_atom_max=20),
    )
    assert r.status_code == 201, r.text
    cand_id = r.json()["candidates"][0]["candidate_id"]
    async with session_factory() as session:
        cand = await session.get(SkillCandidate, cand_id)
        assert cand.payload["target_atom_min"] == 12
        assert cand.payload["target_atom_max"] == 20


# ---------- RBAC 与前置闸 ---------------------------------------------------------

async def test_llm_plan_rbac_and_pre_gates(client, session_factory):
    ps_id = await _make_ps(session_factory)
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan",
        json=_plan_body(actor=REVIEWER),
    )
    assert r.status_code == 403
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan",
        json=_plan_body(actor=CUSTOMER),
    )
    assert r.status_code == 403

    r = await client.post(
        "/api/product-spaces/no-such-ps/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 404

    # 落一个 pending_gate 池：存在且非 rejected → 409，不调模型。
    plan = {
        "dimensions": [_dim(1), _dim(2), _dim(3)],
        "target_atom_min": 15,
        "target_atom_max": 30,
        "actor": OPS,
    }
    r = await client.post(f"/api/product-spaces/{ps_id}/field-pools", json=plan)
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 409

    # rejected 池允许重新触发（与 submit_plan 同口径）。
    current = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    pool_id = current.json()["pool_id"]
    r = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "reject", "reason": "重来", "actor": REVIEWER},
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 201, r.text


# ---------- 预算/Key/坏输出（沿用 Q82-Q84 语义） ----------------------------------

async def test_llm_plan_disabled_model_and_budget_hardstop(client, session_factory):
    ps_id = await _make_ps(session_factory)
    r = await client.patch(
        f"/api/admin/ai-models/{SYNTHETIC_MODEL_ID}",
        json={"status": "disabled", "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 409  # 停用且无 fallback，不静默切供应商

    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-backup", "provider": "synthetic", "actor": PLATFORM_ADMIN,
    })
    backup_id = r.json()["model_id"]
    r = await client.patch(
        f"/api/admin/ai-models/{SYNTHETIC_MODEL_ID}",
        json={"fallback_model_id": backup_id, "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 201 and r.json()["model_id"] == backup_id

    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-zero", "provider": "synthetic",
        "daily_budget": 0, "actor": PLATFORM_ADMIN,
    })
    zero_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_DIM_MERGE}", json={
        "model_id": zero_id, "actor": OPS,
    })
    assert r.status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 409


async def test_llm_plan_remote_model_without_key_is_422(client, session_factory):
    ps_id = await _make_ps(session_factory)
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "gpt-nokey", "provider": "openai", "actor": PLATFORM_ADMIN,
    })
    remote_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_DIM_MERGE}", json={
        "model_id": remote_id, "actor": OPS,
    })
    assert r.status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 422  # 缺 active Key，配置错误，不发起网络调用


async def test_llm_plan_malformed_model_output_is_502(client, session_factory, monkeypatch):
    ps_id = await _make_ps(session_factory)

    async def _broken(self, **kwargs):
        return GenerationResult(text="this is not json", input_tokens=3, output_tokens=4)

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _broken)
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 502


# ---------- 输出严格校验：脏维度/回显漂移一律 502 ----------------------------------

def _patch_builder(monkeypatch, out):
    builders = dict(synthetic.BUILDERS)
    builders[SCENE_DIM_MERGE] = lambda variables: out
    monkeypatch.setattr(synthetic, "BUILDERS", builders)


def _valid_out(**kw):
    out = {
        "target_atom_min": 15,
        "target_atom_max": 30,
        "dimensions": [
            _dim(1, fid="f_a", source_ref="g2:f_a"),
            _dim(2, field_name="维度2b"),
            _dim(3, field_name="维度3b"),
        ],
    }
    out.update(kw)
    return out


async def test_llm_plan_rejects_target_echo_drift(client, session_factory, monkeypatch):
    ps_id = await _make_ps(session_factory)
    _patch_builder(monkeypatch, _valid_out(target_atom_min=16))
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 502


async def test_llm_plan_rejects_dirty_dimensions(client, session_factory, monkeypatch):
    ps_id = await _make_ps(session_factory)

    cases = [
        _valid_out(dimensions=[_dim(1, role="made_up_role"), _dim(2), _dim(3)]),
        _valid_out(dimensions=[_dim(1, source_route="disabled_route"), _dim(2), _dim(3)]),
        _valid_out(dimensions=[_dim(1, fid="ghost_fid"), _dim(2), _dim(3)]),
        _valid_out(dimensions=[_dim(1, fid="-"), _dim(2), _dim(3)]),
        _valid_out(dimensions=[_dim(1, confidence=1.5), _dim(2), _dim(3)]),
        _valid_out(dimensions=[_dim(1, confidence="high"), _dim(2), _dim(3)]),
        _valid_out(dimensions=[_dim(1, source_ref="  "), _dim(2), _dim(3)]),
        _valid_out(dimensions=[_dim(1), _dim(2), _dim(2)]),
        _valid_out(dimensions=[_dim(i) for i in range(9)]),
        _valid_out(dimensions=[]),
    ]
    for out in cases:
        _patch_builder(monkeypatch, out)
        r = await client.post(
            f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
        )
        assert r.status_code == 502, r.text


async def test_llm_plan_confidence_passthrough_marks_needs_detail(
    client, session_factory, monkeypatch
):
    # Q85-3：与 Q83/Q84 不同，confidence 是 PT-FP-PLAN 契约内 AI 字段，透传
    # 给域内 Q9 细看线判定；模型多带的未知键不进候选 payload。
    ps_id = await _make_ps(session_factory)
    _patch_builder(monkeypatch, _valid_out(dimensions=[
        _dim(1, fid="f_a", source_ref="g2:f_a", confidence=0.5, extra_junk="x"),
        _dim(2, confidence=0.95),
        _dim(3, confidence=0.95),
    ]))
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 201, r.text
    cand_id = r.json()["candidates"][0]["candidate_id"]
    async with session_factory() as session:
        cand = await session.get(SkillCandidate, cand_id)
        first = cand.payload["dimensions"][0]
        assert first["confidence"] == 0.5 and "extra_junk" not in first
        assert "similarity" not in first

    ok = await client.post(
        f"/api/skill-candidates/{cand_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert ok.status_code == 200, ok.text
    pool = (await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")).json()
    low = [d for d in pool["dimensions"] if d["confidence"] == 0.5]
    assert low and low[0]["needs_detail"] is True  # Q9 <0.85


async def test_llm_plan_below_min_lands_noncompliant_pool_gate_blocks_approval(
    client, session_factory, monkeypatch
):
    # <3 维不自动补、不 502：属业务违规，落非合规 pending_gate 池由人工裁决。
    ps_id = await _make_ps(session_factory)
    _patch_builder(monkeypatch, _valid_out(dimensions=[
        _dim(1, fid="f_a", source_ref="g2:f_a"),
        _dim(2),
    ]))
    r = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools/llm-plan", json=_plan_body()
    )
    assert r.status_code == 201, r.text
    cand_id = r.json()["candidates"][0]["candidate_id"]
    ok = await client.post(
        f"/api/skill-candidates/{cand_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert ok.status_code == 200, ok.text
    pool = (await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")).json()
    assert pool["gate"] == "pending_gate" and pool["compliant"] is False
    assert "below_min" in pool["violations"]
    gate = await client.post(
        f"/api/field-pools/{pool['pool_id']}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 409  # 非合规方案不允许过 WF-02 Gate
