"""Q83 集成测试：PWC-BUILDER 真 LLM 组合生成（Q82 模式第二站）。

create_all 不跑迁移种子；synthetic 模型 / PWC-BUILDER 场景路由 / Prompt v0.1
由本文件 helper 自插；业务数据（PS/字段池/原子/contentGoals）全部合成（16 §4）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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
    PWC_BUILDER_PROMPT_ID,
    PWC_BUILDER_PROMPT_TEMPLATE,
    PWC_BUILDER_PROMPT_VARIABLES,
    PWC_BUILDER_PROMPT_VERSION,
    SCENE_PWC_BUILDER,
    SYNTHETIC_MODEL_ID,
)
from app.core.skill7.models import SkillCandidate, SkillRun
from app.main import app
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import G2Field

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
            G2Field(fid="f_a", cat="common", field_name="字段A"),
            G2Field(fid="f_b", cat="selling", field_name="字段B"),
            FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
            AIModel(
                model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
                provider="synthetic", status="active",
            ),
            AISceneRoute(scene=SCENE_PWC_BUILDER, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_PWC_BUILDER, current_version=PWC_BUILDER_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=PWC_BUILDER_PROMPT_ID, skill_id=SCENE_PWC_BUILDER,
                version=PWC_BUILDER_PROMPT_VERSION, template=PWC_BUILDER_PROMPT_TEMPLATE,
                variables={"vars": PWC_BUILDER_PROMPT_VARIABLES},
            ),
        ] + [ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _dim(i, **kw):
    base = {
        "field_name": f"维度{i}", "role": "product_attribute",
        "source_route": "user_input", "confidence": 0.9, "source_ref": f"ref-{i}",
    }
    base.update(kw)
    return base


async def _make_ps(session_factory, tenant: str = "t1") -> str:
    from app.product.product_intake.models import (
        ProductIntakeApplication,
        ProductSpace,
    )

    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id=tenant, status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id=tenant, intake_id=intake.intake_id, industry_tag="general",
            profile_snapshot={"f_a": "x"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


async def _approved_pool(client, ps_id: str, dim_count: int = 3):
    resp = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools",
        json={"dimensions": [_dim(i, fid="f_a" if i == 1 else "f_b" if i == 2 else None)
                              for i in range(1, dim_count + 1)], "actor": OPS},
    )
    assert resp.status_code == 200, resp.text
    pool_id = resp.json()["pool_id"]
    gate = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    return pool.json()


async def _approve_atoms(client, ps_id: str, dims: list[str], contents: list[str]):
    resp = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches",
        json={"items": [
            {"content": contents[i], "dimension_id": dims[i],
             "ai_risk": "low", "evidence": "客服语料"}
            for i in range(len(dims))
        ], "actor": OPS},
    )
    assert resp.status_code == 200, resp.text
    for c in resp.json()["candidates"]:
        ok = await client.post(
            f"/api/atom-candidates/{c['candidate_id']}/approve", json={"actor": REVIEWER}
        )
        assert ok.status_code == 200, ok.text


async def _ps_with_atoms(client, session_factory, contents=("温和洁面", "水润肤感", "清爽质地")):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id, dim_count=3)
    dims = [d["dimension_id"] for d in pool["dimensions"][: len(contents)]]
    await _approve_atoms(client, ps_id, dims, list(contents))
    return ps_id


# ---------- 全链路 ----------------------------------------------------------------

async def test_pwc_build_happy_path_then_human_gates(client, session_factory):
    ps_id = await _ps_with_atoms(client, session_factory)

    r = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/llm-build", json={"actor": OPS}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "llm_auto" and body["model_id"] == SYNTHETIC_MODEL_ID
    assert body["input_tokens"] >= 1 and body["output_tokens"] >= 1
    # synthetic：3 维 → 首维锚点 × 其余 2 维 = 2 条候选。
    assert len(body["candidates"]) == 2
    assert all(c["state"] == "pending_review" and c["target_type"] == "pwc_combo"
               for c in body["candidates"])

    async with session_factory() as session:
        run = await session.get(SkillRun, body["run_id"])
        assert run.source == "llm_auto" and run.model_id == SYNTHETIC_MODEL_ID
        assert run.input_cost is not None and run.output_cost is not None
        cand = await session.get(SkillCandidate, body["candidates"][0]["candidate_id"])
        assert cand.state == "pending_review"
        combo = cand.payload["combos"][0]
        assert "logic_score" not in combo and "fit_score" not in combo
        assert len(combo["atom_ids"]) == 2

    # 产品审核员逐候选 confirm → 适配器跑 M5 漏斗（Q22b 子分缺 → incomplete）。
    for c in body["candidates"]:
        r = await client.post(
            f"/api/skill-candidates/{c['candidate_id']}/decision",
            json={"decision": "confirmed", "actor": REVIEWER},
        )
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "applied"

    pwcs = (await client.get(f"/api/product-spaces/{ps_id}/pwcs")).json()
    assert len(pwcs) == 2
    assert all(p["source"] == "ai" and p["score_incomplete"] is True
               and p["status"] == "pending_gate" and p["goals"] == [] for p in pwcs)

    # 再过 PWC 既有产品审核 Gate：approve → ready（评分缺失不阻断人工裁决）。
    r = await client.post(
        f"/api/pwcs/{pwcs[0]['pwc_id']}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"


# ---------- RBAC / 存在性 / 前置状态 ----------------------------------------------

async def test_pwc_build_rbac_notfound_and_pool_gate(client, session_factory):
    ps_id = await _make_ps(session_factory)

    r = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/llm-build", json={"actor": CUSTOMER}
    )
    assert r.status_code == 403

    r = await client.post(
        "/api/product-spaces/no-such-ps/pwc/llm-build", json={"actor": OPS}
    )
    assert r.status_code == 404

    # PS 存在但字段池未 approve → 409。
    r = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/llm-build", json={"actor": OPS}
    )
    assert r.status_code == 409


async def test_pwc_build_atoms_not_spanning_two_dimensions_is_409(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id, dim_count=3)
    dims = [pool["dimensions"][0]["dimension_id"]]
    await _approve_atoms(client, ps_id, dims, ["仅一个维度有原子"])

    r = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/llm-build", json={"actor": OPS}
    )
    assert r.status_code == 409


# ---------- 预算 / Key / 坏输出 ----------------------------------------------------

async def test_pwc_build_budget_hardstop_is_409(client, session_factory):
    ps_id = await _ps_with_atoms(client, session_factory)
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-zero", "provider": "synthetic",
        "daily_budget": 0, "actor": PLATFORM_ADMIN,
    })
    zero_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_PWC_BUILDER}", json={
        "model_id": zero_id, "actor": OPS,
    })
    assert r.status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/llm-build", json={"actor": OPS}
    )
    assert r.status_code == 409


async def test_pwc_build_remote_model_without_key_is_422(client, session_factory):
    ps_id = await _ps_with_atoms(client, session_factory)
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "gpt-nokey", "provider": "openai", "actor": PLATFORM_ADMIN,
    })
    remote_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_PWC_BUILDER}", json={
        "model_id": remote_id, "actor": OPS,
    })
    assert r.status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/llm-build", json={"actor": OPS}
    )
    assert r.status_code == 422


async def test_pwc_build_malformed_model_output_is_502(client, session_factory, monkeypatch):
    ps_id = await _ps_with_atoms(client, session_factory)

    async def _broken(self, **kwargs):
        return GenerationResult(text="not json at all", input_tokens=3, output_tokens=4)

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _broken)
    r = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/llm-build", json={"actor": OPS}
    )
    assert r.status_code == 502


async def test_pwc_build_output_with_unknown_atoms_is_502(client, session_factory, monkeypatch):
    ps_id = await _ps_with_atoms(client, session_factory)
    monkeypatch.setitem(
        synthetic.BUILDERS, SCENE_PWC_BUILDER,
        lambda variables: {"combos": [
            {"atom_ids": ["ghost-1", "ghost-2"], "goals": []}
        ]},
    )
    r = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/llm-build", json={"actor": OPS}
    )
    assert r.status_code == 502


async def test_pwc_build_output_with_injected_scores_is_stripped(client, session_factory, monkeypatch):
    # 模型回带评分：编排层丢弃，落库候选仍无分项（Q83-3/Q22b）。
    ps_id = await _ps_with_atoms(client, session_factory)
    original = synthetic.build_pwc_builder
    monkeypatch.setitem(
        synthetic.BUILDERS, SCENE_PWC_BUILDER,
        lambda variables: {
            "combos": [
                dict(c, logic_score=0.99, fit_score=0.88, weight=0.5)
                for c in original(variables)["combos"]
            ]
        },
    )
    r = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/llm-build", json={"actor": OPS}
    )
    assert r.status_code == 201, r.text
    async with session_factory() as session:
        for c in r.json()["candidates"]:
            cand = await session.get(SkillCandidate, c["candidate_id"])
            combo = cand.payload["combos"][0]
            assert "logic_score" not in combo and "fit_score" not in combo
            assert "weight" not in combo
