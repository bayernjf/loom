"""Q84 集成测试：C7 Layer4（TYPE-MATCH）第三站真 LLM 全链路。

形态与 Q82/Q83 同档：operations 显式端点 → 模型网关（synthetic 确定性替身）→
整 C7ResolveRequest 单候选（c7_layer4，intake 锚点）落 pending_review →
operations Gate 裁决后适配器复用 modeling.resolve_c7（Q6/Q68 四层兜底不绕）。
create_all 不跑迁移种子，平台三行由本文件 helper 自行插入；业务数据全部合成（16 §4）。
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
    SCENE_TYPE_MATCH,
    SYNTHETIC_MODEL_ID,
    TYPE_MATCH_PROMPT_ID,
    TYPE_MATCH_PROMPT_TEMPLATE,
    TYPE_MATCH_PROMPT_VARIABLES,
    TYPE_MATCH_PROMPT_VERSION,
)
from app.core.skill7.models import SkillCandidate, SkillRun
from app.core.tenants.models import Tenant
from app.main import app
from app.product.modeling.models import C7Run, G1Category, G2FieldCandidate
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
            Tenant(tenant_id="t1", name="试点客户", plan="basic", status="active"),
            AIModel(
                model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
                provider="synthetic", status="active",
            ),
            AISceneRoute(scene=SCENE_TYPE_MATCH, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_TYPE_MATCH, current_version=TYPE_MATCH_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=TYPE_MATCH_PROMPT_ID, skill_id=SCENE_TYPE_MATCH,
                version=TYPE_MATCH_PROMPT_VERSION, template=TYPE_MATCH_PROMPT_TEMPLATE,
                variables={"vars": TYPE_MATCH_PROMPT_VARIABLES},
            ),
            G2Field(fid="f_name", cat="common", field_name="产品名"),
            G2Field(fid="f_brief", cat="common", field_name="简介"),
        ])
        session.add(G1Category(name="合成护肤类目", status="active"))
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _category_id(client) -> str:
    r = await client.get("/api/categories")
    cats = r.json()
    return cats[0]["category_id"] if isinstance(cats, list) else cats["categories"][0]


async def _submitted_intake(client) -> str:
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "合成面霜", "f_brief": "保湿"}},
    )
    intake_id = r.json()["intake_id"]
    r = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "submit", "actor": CUSTOMER},
    )
    assert r.status_code == 200, r.text
    return intake_id


def _resolve_body(category_id, *, fids=None, actor=OPS):
    return {
        "category_id": category_id,
        # 1/6 G2 覆盖 < 0.6 → 裁决后落 Layer4（Q6）。
        "required_fids": fids or ["f_name", "m1", "m2", "m3", "m4", "m5"],
        "actor": actor,
    }


async def _count(session_factory, model) -> int:
    async with session_factory() as session:
        return (await session.scalars(select(func.count()).select_from(model))).one()


# ---------- happy path → operations Gate → resolve_c7 Layer4 ---------------------

async def test_llm_resolve_happy_path_then_confirm_layer4(client, session_factory):
    intake_id = await _submitted_intake(client)
    category_id = await _category_id(client)
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "llm_auto"
    assert body["model_id"] == SYNTHETIC_MODEL_ID
    assert body["input_tokens"] >= 1 and body["output_tokens"] >= 1
    assert len(body["candidates"]) == 1
    cand_id = body["candidates"][0]["candidate_id"]
    assert body["candidates"][0] == {
        "candidate_id": cand_id, "state": "pending_review", "target_type": "c7_layer4",
    }

    async with session_factory() as session:
        run = await session.get(SkillRun, body["run_id"])
        assert run.source == "llm_auto" and run.model_id == SYNTHETIC_MODEL_ID
        assert run.input_cost is not None and run.output_cost is not None
        cand = await session.get(SkillCandidate, cand_id)
        assert cand.state == "pending_review"
        assert cand.payload["category_id"] == category_id
        assert cand.payload["required_fids"] == ["f_name", "m1", "m2", "m3", "m4", "m5"]
        names = [p["field_name"] for p in cand.payload["l4_proposals"]]
        assert names == ["待补字段·m1", "待补字段·m2", "待补字段·m3", "待补字段·m4", "待补字段·m5"]
        # 模型侧任何分/路由字段都不得进候选 payload（Q84-3）。
        assert "confidence" not in cand.payload
        assert all(set(p) == {"field_name", "definition"} for p in cand.payload["l4_proposals"])
    assert await _count(session_factory, C7Run) == 0  # 未裁前不跑 C7

    r = await client.post(
        f"/api/skill-candidates/{cand_id}/decision",
        json={"decision": "confirmed", "actor": OPS},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "applied"
    async with session_factory() as session:
        c7_run = (await session.scalars(select(C7Run))).one()
        assert c7_run.layer == 4
        rows = list((await session.scalars(select(G2FieldCandidate))).all())
    assert len(rows) == 5
    assert {r.source_layer for r in rows} == {"c7_layer4"}
    assert all(r.status == "pending_gate" for r in rows)  # Q13 转正 Gate 不在本切片


async def test_full_coverage_delivers_empty_proposals_and_lands_layer3(
    client, session_factory
):
    intake_id = await _submitted_intake(client)
    category_id = await _category_id(client)
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id, fids=["f_name", "f_brief"]),
    )
    assert r.status_code == 201, r.text
    cand_id = r.json()["candidates"][0]["candidate_id"]
    async with session_factory() as session:
        cand = await session.get(SkillCandidate, cand_id)
        assert cand.payload["l4_proposals"] == []  # 覆盖足 → 空提案合法（Q84-2）

    ok = await client.post(
        f"/api/skill-candidates/{cand_id}/decision",
        json={"decision": "confirmed", "actor": OPS},
    )
    assert ok.status_code == 200, ok.text
    async with session_factory() as session:
        c7_run = (await session.scalars(select(C7Run))).one()
        assert c7_run.layer == 3 and c7_run.detail["coverage"] == 1.0
    assert await _count(session_factory, G2FieldCandidate) == 0


# ---------- RBAC 与前置闸 ---------------------------------------------------------

async def test_llm_resolve_rbac_and_pre_gates(client):
    intake_id = await _submitted_intake(client)
    category_id = await _category_id(client)

    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id, actor=REVIEWER),
    )
    assert r.status_code == 403
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id, actor=CUSTOMER),
    )
    assert r.status_code == 403

    r = await client.post(
        "/api/intakes/no-such-intake/c7/llm-resolve",
        json=_resolve_body(category_id),
    )
    assert r.status_code == 404

    # 类目不存在 → 404。
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body("cat-nope"),
    )
    assert r.status_code == 404

    # 草稿单不在 ai_recognizing → 409。
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "面霜"}},
    )
    draft_id = r.json()["intake_id"]
    r = await client.post(
        f"/api/intakes/{draft_id}/c7/llm-resolve",
        json=_resolve_body(category_id),
    )
    assert r.status_code == 409

    # Q68：必填 fid:'-' 调模型前就拦 422。
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id, fids=["f_name", "-"]),
    )
    assert r.status_code == 422


async def test_llm_resolve_draft_category_is_409(client, session_factory):
    intake_id = await _submitted_intake(client)
    async with session_factory() as session:
        session.add(G1Category(name="草稿类目", status="draft"))
        await session.commit()
        draft_cat = (await session.scalars(
            select(G1Category).where(G1Category.name == "草稿类目")
        )).one()
        draft_cat_id = draft_cat.category_id
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(draft_cat_id),
    )
    assert r.status_code == 409


# ---------- 预算/Key/坏输出（沿用 Q82/Q83 语义） ----------------------------------

async def test_llm_resolve_disabled_model_and_budget_hardstop(client):
    intake_id = await _submitted_intake(client)
    category_id = await _category_id(client)
    r = await client.patch(
        f"/api/admin/ai-models/{SYNTHETIC_MODEL_ID}",
        json={"status": "disabled", "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 200
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id),
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
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id),
    )
    assert r.status_code == 201 and r.json()["model_id"] == backup_id

    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-zero", "provider": "synthetic",
        "daily_budget": 0, "actor": PLATFORM_ADMIN,
    })
    zero_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_TYPE_MATCH}", json={
        "model_id": zero_id, "actor": OPS,
    })
    assert r.status_code == 200
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id),
    )
    assert r.status_code == 409


async def test_llm_resolve_remote_model_without_key_is_422(client):
    intake_id = await _submitted_intake(client)
    category_id = await _category_id(client)
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "gpt-nokey", "provider": "openai", "actor": PLATFORM_ADMIN,
    })
    remote_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_TYPE_MATCH}", json={
        "model_id": remote_id, "actor": OPS,
    })
    assert r.status_code == 200
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id),
    )
    assert r.status_code == 422  # 缺 active Key，配置错误，不发起网络调用


async def test_llm_resolve_malformed_model_output_is_502(client, monkeypatch):
    intake_id = await _submitted_intake(client)
    category_id = await _category_id(client)

    async def _broken(self, **kwargs):
        return GenerationResult(text="this is not json", input_tokens=3, output_tokens=4)

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _broken)
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id),
    )
    assert r.status_code == 502


# ---------- 输出严格校验：越界回显/脏提案一律 502，分一律剥离 ----------------------

def _patch_builder(monkeypatch, out):
    builders = dict(synthetic.BUILDERS)
    builders[SCENE_TYPE_MATCH] = lambda variables: out
    monkeypatch.setattr(synthetic, "BUILDERS", builders)


async def test_llm_resolve_rejects_category_mismatch(client, monkeypatch):
    intake_id = await _submitted_intake(client)
    category_id = await _category_id(client)
    _patch_builder(monkeypatch, {
        "category_id": "cat-other",
        "required_fids": ["f_name"],
        "l4_proposals": [],
    })
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id, fids=["f_name"]),
    )
    assert r.status_code == 502


async def test_llm_resolve_rejects_required_fids_echo_drift(client, monkeypatch):
    intake_id = await _submitted_intake(client)
    category_id = await _category_id(client)
    _patch_builder(monkeypatch, {
        "category_id": category_id,
        "required_fids": ["f_name", "ghost_fid"],
        "l4_proposals": [],
    })
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id, fids=["f_name"]),
    )
    assert r.status_code == 502


async def test_llm_resolve_rejects_dirty_proposals(client, monkeypatch):
    intake_id = await _submitted_intake(client)
    category_id = await _category_id(client)

    _patch_builder(monkeypatch, {
        "category_id": category_id,
        "required_fids": ["f_name", "m1"],
        "l4_proposals": [{"field_name": "黑户", "fid": "-"}],
    })
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id, fids=["f_name", "m1"]),
    )
    assert r.status_code == 502

    _patch_builder(monkeypatch, {
        "category_id": category_id,
        "required_fids": ["f_name", "m1"],
        "l4_proposals": [{"definition": "缺名字"}],
    })
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id, fids=["f_name", "m1"]),
    )
    assert r.status_code == 502


async def test_llm_resolve_strips_model_scores_and_route_fields(
    client, session_factory, monkeypatch
):
    intake_id = await _submitted_intake(client)
    category_id = await _category_id(client)
    _patch_builder(monkeypatch, {
        "category_id": category_id,
        "required_fids": ["f_name", "m1"],
        "confidence": 0.99,
        "l4_proposals": [{
            "field_name": "模型新字段",
            "definition": "  ",
            "confidence": 0.71,
            "score": 12,
            "fid": "m1",
            "source_route": "made_up_route",
            "status": "approved",
        }],
    })
    r = await client.post(
        f"/api/intakes/{intake_id}/c7/llm-resolve",
        json=_resolve_body(category_id, fids=["f_name", "m1"]),
    )
    assert r.status_code == 201, r.text
    cand_id = r.json()["candidates"][0]["candidate_id"]
    async with session_factory() as session:
        cand = await session.get(SkillCandidate, cand_id)
        assert "confidence" not in cand.payload
        assert cand.payload["l4_proposals"] == [{"field_name": "模型新字段"}]
