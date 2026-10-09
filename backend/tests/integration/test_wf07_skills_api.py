"""WF-07 AI 选包四 Skill 场景集成测试（Q326 场景注册）：四场景路由＋Prompt
v0.1 就位后，gateway.invoke 经 synthetic 驱动返回确定性字典值候选。

create_all 不跑迁移种子；synthetic 模型与四场景路由/Prompt v0.1 由本文件
fixture 自插。触发/候选展示/人工采用操作面随 design 候选档裁决后另点工。
"""

import json

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.model_registry import gateway as gw
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
from app.main import app  # noqa: F401  (注册全量模型进 Base.metadata)

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
    async with factory() as session:
        records = [
            AIModel(
                model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
                provider="synthetic", status="active",
            )
        ]
        for scene, version, prompt_id, template, variables in _SCENES:
            records.append(AISceneRoute(scene=scene, model_id=SYNTHETIC_MODEL_ID))
            records.append(SkillPrompt(skill_id=scene, current_version=version))
            records.append(SkillPromptVersion(
                version_id=prompt_id, skill_id=scene, version=version,
                template=template, variables={"vars": variables},
            ))
        session.add_all(records)
        await session.commit()
    yield factory
    await engine.dispose()


async def test_invoke_goal_plan_returns_candidates(session_factory):
    async with session_factory() as session:
        invocation = await gw.invoke(
            session, SCENE_PT_CONTENT_GOAL_PLAN,
            {
                "profile_snapshot": {"brand": "acme"},
                "platform": "wechat", "slot": {}, "industry_tag": "beauty",
                "sensitive": False,
            },
        )
    payload = json.loads(invocation.text)
    assert len(payload["goals"]) <= 3
    assert payload["goals"][0]["goal"] == "ENGAGEMENT"
    assert invocation.provider == "synthetic"


async def test_invoke_goal_plan_empty_without_profile(session_factory):
    async with session_factory() as session:
        invocation = await gw.invoke(
            session, SCENE_PT_CONTENT_GOAL_PLAN,
            {
                "profile_snapshot": {}, "platform": "wechat", "slot": {},
                "industry_tag": "", "sensitive": False,
            },
        )
    assert json.loads(invocation.text) == {"goals": []}


async def test_invoke_struct_match_partial_without_constraint(session_factory):
    async with session_factory() as session:
        invocation = await gw.invoke(
            session, SCENE_PT_STRUCT_MATCH,
            {"profile_snapshot": {"brand": "acme"}, "slot": {}},
        )
    payload = json.loads(invocation.text)
    assert len(payload["structures"]) <= 2
    assert all(s["partial"] is True for s in payload["structures"])


async def test_invoke_tone_style(session_factory):
    async with session_factory() as session:
        invocation = await gw.invoke(
            session, SCENE_PT_TONE_STYLE,
            {"goal": "ENGAGEMENT", "platform": "wechat", "industry_tag": "beauty"},
        )
    payload = json.loads(invocation.text)
    assert set(payload.keys()) == {"tone", "style"}


async def test_invoke_goal_tag_confirms(session_factory):
    async with session_factory() as session:
        invocation = await gw.invoke(
            session, SCENE_PT_CONTENT_GOAL_TAG,
            {"body": "已生成正文", "goal": "TRUST"},
        )
    assert json.loads(invocation.text) == {
        "goal": "TRUST", "confirmed": True, "confidence": 0.88,
    }
