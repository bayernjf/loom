"""Q328 WF-07 操作面集成测试：/api/ai-select/suggest 触发 ＋ package_draft 裁决。

口径（design-video-studio-segment-cleaning §5，D3/D4 甲，D5＝Package 草稿/operations）：
- suggest 按当前 PS×platform×slot 组装有界变量 → 模型网关 synthetic 路由
  （Q326 场景注册）→ skill7 投递通道落 skill_candidates（pending_review）＋
  SLA 待办＋审计；AI 只产候选不自动生效；
- 前置闸：PS 存在（404）、TONE/TAG 缺 goal、TAG 缺 body 由合成路由 error 形态
  按 422 强校验；投递角色闸 operations（客户 403）；
- decide（operations）confirmed/modified → apply_package_draft 字典强校验
  （越字典值 422），命中 → applied＋applied_refs；采用后的预填在前端走既有
  包 create/update 审批，适配器不写包表、不绕过包 Gate。

create_all 不跑迁移种子；synthetic 模型、四场景路由/Prompt、ContentGoal、
Q43 17 池（struct/tone/style）、ProductSpace 由本文件 fixture 自插。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.model_registry.models import (
    AIModel,
    AISceneRoute,
    SkillPrompt,
    SkillPromptVersion,
)
from app.core.model_registry.seeds import (
    PT_CONTENT_GOAL_PLAN_PROMPT_ID,
    PT_CONTENT_GOAL_PLAN_TEMPLATE,
    PT_CONTENT_GOAL_PLAN_VARIABLES,
    PT_CONTENT_GOAL_PLAN_VERSION,
    PT_CONTENT_GOAL_TAG_PROMPT_ID,
    PT_CONTENT_GOAL_TAG_TEMPLATE,
    PT_CONTENT_GOAL_TAG_VARIABLES,
    PT_CONTENT_GOAL_TAG_VERSION,
    PT_STRUCT_MATCH_PROMPT_ID,
    PT_STRUCT_MATCH_TEMPLATE,
    PT_STRUCT_MATCH_VARIABLES,
    PT_STRUCT_MATCH_VERSION,
    PT_TONE_STYLE_PROMPT_ID,
    PT_TONE_STYLE_TEMPLATE,
    PT_TONE_STYLE_VARIABLES,
    PT_TONE_STYLE_VERSION,
    SCENE_PT_CONTENT_GOAL_PLAN,
    SCENE_PT_CONTENT_GOAL_TAG,
    SCENE_PT_STRUCT_MATCH,
    SCENE_PT_TONE_STYLE,
    SYNTHETIC_MODEL_ID,
)
from app.core.pool_options.models import ACTIVE, PoolOption
from app.main import app
from app.product.condition.models import ContentGoal
from tests.integration.test_fcw_api import OPS, _make_ps

SUGGEST_PATH = "/api/ai-select/suggest"
CUSTOMER = {"id": "cust-1", "roles": []}

_SCENES = (
    (SCENE_PT_CONTENT_GOAL_PLAN, PT_CONTENT_GOAL_PLAN_VERSION,
     PT_CONTENT_GOAL_PLAN_PROMPT_ID, PT_CONTENT_GOAL_PLAN_TEMPLATE,
     PT_CONTENT_GOAL_PLAN_VARIABLES),
    (SCENE_PT_STRUCT_MATCH, PT_STRUCT_MATCH_VERSION,
     PT_STRUCT_MATCH_PROMPT_ID, PT_STRUCT_MATCH_TEMPLATE,
     PT_STRUCT_MATCH_VARIABLES),
    (SCENE_PT_TONE_STYLE, PT_TONE_STYLE_VERSION,
     PT_TONE_STYLE_PROMPT_ID, PT_TONE_STYLE_TEMPLATE,
     PT_TONE_STYLE_VARIABLES),
    (SCENE_PT_CONTENT_GOAL_TAG, PT_CONTENT_GOAL_TAG_VERSION,
     PT_CONTENT_GOAL_TAG_PROMPT_ID, PT_CONTENT_GOAL_TAG_TEMPLATE,
     PT_CONTENT_GOAL_TAG_VARIABLES),
)


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
    async with factory() as session:
        session.add(AIModel(
            model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
            provider="synthetic", status="active",
        ))
        for scene, version, prompt_id, template, variables in _SCENES:
            session.add(AISceneRoute(scene=scene, model_id=SYNTHETIC_MODEL_ID))
            session.add(SkillPrompt(skill_id=scene, current_version=version))
            session.add(SkillPromptVersion(
                version_id=prompt_id, skill_id=scene, version=version,
                template=template, variables={"vars": variables},
            ))
        for code in ("ENGAGEMENT", "TRUST"):
            session.add(ContentGoal(code=code, status="active"))
        session.add(PoolOption(pool="struct", options=["钩子-论点-收尾"], status=ACTIVE))
        session.add(PoolOption(pool="tone", options=["温和"], status=ACTIVE))
        session.add(PoolOption(pool="style", options=["口语化"], status=ACTIVE))
        await session.commit()
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_suggest_goal_plan_creates_pending_candidates(client, session_factory):
    ps_id = await _make_ps(session_factory)
    resp = await client.post(SUGGEST_PATH, json={
        "scene": "PT-CONTENT-GOAL-PLAN",
        "product_space_id": ps_id,
        "actor": OPS,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["candidates"]) == 1
    cand = body["candidates"][0]
    assert cand["state"] == "pending_review"
    assert cand["target_type"] == "package_draft"
    assert cand["wf_id"] == "WF-07"
    goals = cand["payload"]["goals"]
    assert goals and all(g["goal"] in {"ENGAGEMENT", "TRUST"} for g in goals)
    run = body["run"]
    assert run["source"] == "delivery"
    assert run["skill_id"] == "PT-CONTENT-GOAL-PLAN"
    assert run["product_space_id"] == ps_id


async def test_suggest_tone_style_requires_goal(client, session_factory):
    ps_id = await _make_ps(session_factory)
    resp = await client.post(SUGGEST_PATH, json={
        "scene": "PT-TONE-STYLE",
        "product_space_id": ps_id,
        "actor": OPS,
    })
    assert resp.status_code == 422, resp.text
    # 模板渲染层先于合成路由拦截缺 goal（variables 组装后即模板校验）。
    assert "missing: goal" in resp.json()["detail"]


async def test_suggest_goal_tag_requires_body(client, session_factory):
    ps_id = await _make_ps(session_factory)
    resp = await client.post(SUGGEST_PATH, json={
        "scene": "PT-CONTENT-GOAL-TAG",
        "product_space_id": ps_id,
        "goal": "ENGAGEMENT",
        "actor": OPS,
    })
    assert resp.status_code == 422, resp.text
    assert "missing: body" in resp.json()["detail"]


async def test_suggest_rejects_non_operations_actor(client, session_factory):
    ps_id = await _make_ps(session_factory)
    resp = await client.post(SUGGEST_PATH, json={
        "scene": "PT-CONTENT-GOAL-PLAN",
        "product_space_id": ps_id,
        "actor": CUSTOMER,
    })
    assert resp.status_code == 403, resp.text


async def test_suggest_ps_missing_returns_404(client):
    resp = await client.post(SUGGEST_PATH, json={
        "scene": "PT-CONTENT-GOAL-PLAN",
        "product_space_id": "no-such-ps",
        "actor": OPS,
    })
    assert resp.status_code == 404, resp.text


async def test_decide_package_draft_confirmed_applies(client, session_factory):
    ps_id = await _make_ps(session_factory)
    resp = await client.post(SUGGEST_PATH, json={
        "scene": "PT-CONTENT-GOAL-PLAN",
        "product_space_id": ps_id,
        "actor": OPS,
    })
    assert resp.status_code == 201, resp.text
    cand = resp.json()["candidates"][0]
    decide = await client.post(
        f"/api/skill-candidates/{cand['candidate_id']}/decision",
        json={"decision": "confirmed", "reason": "按推荐", "actor": OPS},
    )
    assert decide.status_code == 200, decide.text
    updated = decide.json()
    assert updated["state"] == "applied"
    assert updated["applied_refs"] and updated["applied_refs"][0].startswith("goal:")


async def test_decide_package_draft_modified_outside_dictionary_rejected(
    client, session_factory
):
    ps_id = await _make_ps(session_factory)
    resp = await client.post(SUGGEST_PATH, json={
        "scene": "PT-CONTENT-GOAL-PLAN",
        "product_space_id": ps_id,
        "actor": OPS,
    })
    cand = resp.json()["candidates"][0]
    decide = await client.post(
        f"/api/skill-candidates/{cand['candidate_id']}/decision",
        json={
            "decision": "modified",
            "payload": {"goals": [{"goal": "NOT-IN-DICTIONARY", "confidence": 0.9}]},
            "actor": OPS,
        },
    )
    assert decide.status_code == 422, decide.text
    assert "not in ContentGoal" in decide.json()["detail"]


async def test_decide_package_draft_rejected_archives(client, session_factory):
    ps_id = await _make_ps(session_factory)
    resp = await client.post(SUGGEST_PATH, json={
        "scene": "PT-CONTENT-GOAL-PLAN",
        "product_space_id": ps_id,
        "actor": OPS,
    })
    cand = resp.json()["candidates"][0]
    decide = await client.post(
        f"/api/skill-candidates/{cand['candidate_id']}/decision",
        json={"decision": "rejected", "reason": "目标不符", "actor": OPS},
    )
    assert decide.status_code == 200, decide.text
    assert decide.json()["state"] == "archived"
