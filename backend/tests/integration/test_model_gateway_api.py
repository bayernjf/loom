"""Q82 集成测试：模型注册表/Key/路由/Prompt 管理 API + CAT-RECOG 试点全链路。

create_all 不跑迁移种子，平台三行（合成模型/场景路由/Prompt v0.1）由本文件
helper 自行插入；业务数据（信号权重/阈值/G1 类目/intake）全部合成（16 §4）。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.actor import Actor
from app.core.db import Base, get_session
from app.core.model_registry import drivers, gateway
from app.core.model_registry.drivers import GenerationResult
from app.core.model_registry.models import (
    AIModel,
    AISceneRoute,
    SkillPrompt,
    SkillPromptVersion,
)
from app.core.model_registry.schemas import PromptPublish, SceneRouteUpsert
from app.core.model_registry.seeds import (
    CAT_RECOG_PROMPT_ID,
    CAT_RECOG_PROMPT_TEMPLATE,
    CAT_RECOG_PROMPT_VARIABLES,
    CAT_RECOG_PROMPT_VERSION,
    SCENE_CAT_RECOG,
    SYNTHETIC_MODEL_ID,
)
from app.core.skill7.models import SkillCandidate, SkillRun
from app.main import app
from app.product.modeling.models import (
    C1IndustryThreshold,
    C1SignalWeight,
    G1Category,
)
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import G2Field

OPS = {"id": "ops-1", "roles": ["operations"]}
PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}


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


async def _seed_platform(session: AsyncSession) -> None:
    """迁移 0014 的种子三行 + 指针（测试不跑迁移）。"""
    session.add_all([
        AIModel(
            model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
            provider="synthetic", status="active",
        ),
        AISceneRoute(scene=SCENE_CAT_RECOG, model_id=SYNTHETIC_MODEL_ID),
        SkillPrompt(skill_id=SCENE_CAT_RECOG, current_version=CAT_RECOG_PROMPT_VERSION),
        SkillPromptVersion(
            version_id=CAT_RECOG_PROMPT_ID, skill_id=SCENE_CAT_RECOG,
            version=CAT_RECOG_PROMPT_VERSION, template=CAT_RECOG_PROMPT_TEMPLATE,
            variables={"vars": CAT_RECOG_PROMPT_VARIABLES},
        ),
    ])


@pytest_asyncio.fixture
async def client(session_factory):
    async with session_factory() as session:
        await _seed_platform(session)
        session.add_all([
            G2Field(fid="f_name", cat="common", field_name="产品名"),
            G2Field(fid="f_brief", cat="common", field_name="简介"),
            C1SignalWeight(signal="name", signal_name="产品名", enabled=True, weight=0.50),
            C1SignalWeight(signal="brief", signal_name="简介", enabled=True, weight=0.33),
            C1SignalWeight(signal="sellpoint", signal_name="卖点", enabled=True, weight=0.17),
            C1IndustryThreshold(
                industry="general", keywords=[], threshold=0.85,
                sensitive=False, is_default=True,
            ),
            G1Category(name="护肤面霜", status="active"),
            G1Category(name="护肤乳液", status="active"),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _submitted_intake(client) -> str:
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "面霜", "f_brief": "保湿修护"}},
    )
    intake_id = r.json()["intake_id"]
    r = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "submit", "actor": CUSTOMER},
    )
    assert r.status_code == 200, r.text
    return intake_id


# ---------- 模型注册表 -----------------------------------------------------------

async def test_model_crud_rbac_and_validation(client):
    payload = {
        "model_code": "gpt-x", "provider": "openai",
        "input_price_per_1m": 10.0, "output_price_per_1m": 30.0,
        "currency_code": "CNY", "daily_budget": 5,
        "actor": PLATFORM_ADMIN,
    }
    r = await client.post("/api/admin/ai-models", json={**payload, "actor": CUSTOMER})
    assert r.status_code == 403
    r = await client.post("/api/admin/ai-models", json={**payload, "actor": OPS})
    assert r.status_code == 403  # 模型注册=platform_admin 红线（Q82-3）

    r = await client.post("/api/admin/ai-models", json={**payload, "fallback_model_id": "x"})
    assert r.status_code == 422  # 创建时不可挂 fallback

    r = await client.post("/api/admin/ai-models", json=payload)
    assert r.status_code == 201, r.text
    model = r.json()
    assert model["status"] == "active" and model["has_active_key"] is False
    assert model["currency_code"] == "CNY"

    r = await client.post("/api/admin/ai-models", json=payload)
    assert r.status_code == 422  # model_code 唯一

    r = await client.get("/api/admin/ai-models")
    codes = {row["model_code"] for row in r.json()}
    assert {"synthetic-deterministic", "gpt-x"} <= codes

    # 自引用/不存在 fallback 拒绝；404。
    r = await client.patch(
        f"/api/admin/ai-models/{model['model_id']}",
        json={"fallback_model_id": model["model_id"], "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 422
    r = await client.patch(
        f"/api/admin/ai-models/{model['model_id']}",
        json={"fallback_model_id": "no-such-model", "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 422
    r = await client.patch(
        "/api/admin/ai-models/no-such-model",
        json={"status": "disabled", "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 404
    r = await client.patch(
        f"/api/admin/ai-models/{model['model_id']}",
        json={"daily_budget": 9.9, "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 200 and r.json()["daily_budget"] == 9.9


# ---------- Key 生命周期 ----------------------------------------------------------

async def test_key_lifecycle_never_returns_plaintext(client):
    # 先建一个远程模型。
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "gpt-k", "provider": "openai", "actor": PLATFORM_ADMIN,
    })
    model_id = r.json()["model_id"]

    r = await client.post(
        f"/api/admin/ai-models/{model_id}/keys",
        json={"secret": "sk-first-secret", "actor": OPS},
    )
    assert r.status_code == 403
    r = await client.post(
        f"/api/admin/ai-models/{model_id}/keys",
        json={"secret": "sk-first-secret", "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 201, r.text
    key1 = r.json()
    assert key1["fingerprint"] == "cret" and key1["status"] == "active"
    assert "secret" not in r.text and "ciphertext" not in r.text

    # 轮换：旧钥 revoked，新钥 active。
    r = await client.post(
        f"/api/admin/ai-models/{model_id}/keys",
        json={"secret": "sk-second-secret", "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 201 and r.json()["fingerprint"] == "cret"
    r = await client.get(f"/api/admin/ai-models/{model_id}/keys")
    rows = r.json()
    assert len(rows) == 2
    assert sorted(k["status"] for k in rows) == ["active", "revoked"]

    # 模型列表 has_active_key 翻正。
    r = await client.get("/api/admin/ai-models")
    view = next(m for m in r.json() if m["model_id"] == model_id)
    assert view["has_active_key"] is True

    r = await client.post(
        f"/api/admin/ai-model-keys/{key1['key_id']}/revoke",
        json={"actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 200 and r.json()["status"] == "revoked"


# ---------- 场景路由 --------------------------------------------------------------

async def test_scene_routes_operations_may_change(client):
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "gpt-r", "provider": "openai", "actor": PLATFORM_ADMIN,
    })
    model_id = r.json()["model_id"]

    r = await client.put("/api/admin/ai-scene-routes/PWC-BUILDER", json={
        "model_id": "missing", "actor": OPS,
    })
    assert r.status_code == 422
    r = await client.put("/api/admin/ai-scene-routes/PWC-BUILDER", json={
        "model_id": model_id, "actor": CUSTOMER,
    })
    assert r.status_code == 403
    r = await client.put("/api/admin/ai-scene-routes/PWC-BUILDER", json={
        "model_id": model_id, "actor": OPS,
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"scene": "PWC-BUILDER", "model_id": model_id}
    routes = (await client.get("/api/admin/ai-scene-routes")).json()
    assert {row["scene"] for row in routes} == {"CAT-RECOG", "PWC-BUILDER"}


# ---------- Prompt 版本化 ---------------------------------------------------------

async def test_prompt_versioning_is_append_only(client):
    url = "/api/admin/skill-prompts/PWC-BUILDER/versions"
    r = await client.post(url, json={
        "template": "输出 JSON：$product_profile", "change_note": "首版",
        "variables": {"product_profile": "资料"}, "actor": OPS,
    })
    assert r.status_code == 403
    r = await client.post(url, json={
        "template": "输出 JSON：$product_profile", "change_note": "首版",
        "variables": {"product_profile": "资料"}, "actor": PLATFORM_ADMIN,
    })
    assert r.status_code == 201, r.text
    assert r.json()["version"] == "v0.1"
    r = await client.post(url, json={
        "template": "输出严格 JSON：$product_profile", "change_note": "收紧",
        "actor": PLATFORM_ADMIN,
    })
    assert r.status_code == 201 and r.json()["version"] == "v0.2"

    rows = (await client.get(url)).json()
    assert [row["version"] for row in rows] == ["v0.2", "v0.1"]
    assert all("template" not in row for row in rows)  # 列表不回全文

    r = await client.get(f"{url}/v0.1")
    assert r.status_code == 200
    assert r.json()["template"].startswith("输出 JSON")
    assert r.json()["variables"] == {"product_profile": "资料"}

    pointers = (await client.get("/api/admin/skill-prompts")).json()
    pointer = next(row for row in pointers if row["skill_id"] == "PWC-BUILDER")
    assert pointer["current_version"] == "v0.2"


# ---------- CAT-RECOG 试点 ---------------------------------------------------------

async def test_llm_invoke_happy_path_then_human_gate(client, session_factory):
    intake_id = await _submitted_intake(client)
    r = await client.post(
        f"/api/intakes/{intake_id}/c1-recognition/llm-invoke",
        json={"actor": OPS},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "llm_auto"
    assert body["model_id"] == SYNTHETIC_MODEL_ID
    assert body["input_tokens"] >= 1 and body["output_tokens"] >= 1
    assert len(body["candidates"]) == 1
    cand_id = body["candidates"][0]["candidate_id"]
    assert body["candidates"][0] == {
        "candidate_id": cand_id, "state": "pending_review",
        "target_type": "c1_recognition",
    }

    async with session_factory() as session:
        run = await session.get(SkillRun, body["run_id"])
        assert run.source == "llm_auto" and run.model_id == SYNTHETIC_MODEL_ID
        assert run.input_cost is not None and run.output_cost is not None
        cand = await session.get(SkillCandidate, cand_id)
        assert cand.state == "pending_review"
        assert set(cand.payload["signals"]) == {"name", "brief", "sellpoint"}
        assert len(cand.payload["candidates"]) == 2

    # 运营人工 Gate：confirm → 适配器跑 Q1 机械分支（中置信 → ops_assist 待办）。
    r = await client.post(
        f"/api/skill-candidates/{cand_id}/decision",
        json={"decision": "confirmed", "actor": OPS},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "applied"
    r = await client.get(f"/api/intakes/{intake_id}")
    assert r.json()["status"] == sm.PENDING_CONFIRM


async def test_llm_invoke_rbac_and_state_errors(client):
    intake_id = await _submitted_intake(client)
    r = await client.post(
        f"/api/intakes/{intake_id}/c1-recognition/llm-invoke",
        json={"actor": REVIEWER},
    )
    assert r.status_code == 403

    r = await client.post(
        "/api/intakes/no-such-intake/c1-recognition/llm-invoke",
        json={"actor": OPS},
    )
    assert r.status_code == 404

    # 未 submit 的草稿单不在 ai_recognizing → 409。
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "面霜"}},
    )
    draft_id = r.json()["intake_id"]
    r = await client.post(
        f"/api/intakes/{draft_id}/c1-recognition/llm-invoke",
        json={"actor": OPS},
    )
    assert r.status_code == 409


async def test_llm_invoke_disabled_model_and_budget_hardstop(client):
    intake_id = await _submitted_intake(client)

    # 停用且无 fallback → 409（不静默切换供应商）。
    r = await client.patch(
        f"/api/admin/ai-models/{SYNTHETIC_MODEL_ID}",
        json={"status": "disabled", "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 200
    r = await client.post(
        f"/api/intakes/{intake_id}/c1-recognition/llm-invoke", json={"actor": OPS}
    )
    assert r.status_code == 409

    # 再挂一个 active fallback → 解析到 fallback，调用成功。
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
        f"/api/intakes/{intake_id}/c1-recognition/llm-invoke", json={"actor": OPS}
    )
    assert r.status_code == 201 and r.json()["model_id"] == backup_id

    # 日预算 0：首调即硬停 409。
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-zero", "provider": "synthetic",
        "daily_budget": 0, "actor": PLATFORM_ADMIN,
    })
    zero_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_CAT_RECOG}", json={
        "model_id": zero_id, "actor": OPS,
    })
    assert r.status_code == 200
    r = await client.post(
        f"/api/intakes/{intake_id}/c1-recognition/llm-invoke", json={"actor": OPS}
    )
    assert r.status_code == 409


async def test_llm_invoke_remote_model_without_key_is_422(client):
    intake_id = await _submitted_intake(client)
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "gpt-nokey", "provider": "openai", "actor": PLATFORM_ADMIN,
    })
    remote_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_CAT_RECOG}", json={
        "model_id": remote_id, "actor": OPS,
    })
    assert r.status_code == 200
    r = await client.post(
        f"/api/intakes/{intake_id}/c1-recognition/llm-invoke", json={"actor": OPS}
    )
    assert r.status_code == 422  # 缺 active Key，配置错误，不发起网络调用


async def test_llm_invoke_malformed_model_output_is_502(client, monkeypatch):
    intake_id = await _submitted_intake(client)

    async def _broken(self, **kwargs):
        return GenerationResult(text="this is not json", input_tokens=3, output_tokens=4)

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _broken)
    r = await client.post(
        f"/api/intakes/{intake_id}/c1-recognition/llm-invoke", json={"actor": OPS}
    )
    assert r.status_code == 502


# ---------- 服务层直测：路由/Prompt 配置缺失 --------------------------------------

async def test_invoke_configuration_errors(session_factory):
    async with session_factory() as session:
        await _seed_platform(session)
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(gateway.ModelConfigError):
            await gateway.invoke(session, "NO-SUCH-SCENE", {})

    async with session_factory() as session:
        session.add(AIModel(model_code="syn-2", provider="synthetic"))
        await session.flush()
        syn2 = (await session.scalars(
            select(AIModel).where(AIModel.model_code == "syn-2")
        )).first()
        await gateway.upsert_route(
            session, "EMPTY-SCENE",
            SceneRouteUpsert(model_id=syn2.model_id, actor=Actor(**OPS)),
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(gateway.ModelConfigError):  # 场景有路由但无 Prompt
            await gateway.invoke(session, "EMPTY-SCENE", {})

    async with session_factory() as session:
        # Prompt 模板变量缺失同样 422 档配置错误。
        await gateway.publish_prompt(
            session, "EMPTY-SCENE",
            PromptPublish(template="需要 $missing_var", actor=Actor(**PLATFORM_ADMIN)),
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(gateway.ModelConfigError):
            await gateway.invoke(session, "EMPTY-SCENE", {})
