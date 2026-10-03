"""PLATFORM-ADAPTER 场景集成测试（V1 引擎预备，Q260）：场景路由＋Prompt v0.1 就位后，
gateway.invoke 经 synthetic 驱动返回确定性四态建议。

create_all 不跑迁移种子；synthetic 模型与 PLATFORM-ADAPTER 场景路由/Prompt v0.1
由本文件 fixture 自插。业务接线（候选投递/HumanGate/平台审核员界面）随 V2 后续片。
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
    PLATFORM_ADAPTER_PROMPT_ID,
    PLATFORM_ADAPTER_PROMPT_TEMPLATE,
    PLATFORM_ADAPTER_PROMPT_VARIABLES,
    PLATFORM_ADAPTER_PROMPT_VERSION,
    SCENE_PLATFORM_ADAPTER,
    SYNTHETIC_MODEL_ID,
)
from app.main import app  # noqa: F401  (注册全量模型进 Base.metadata)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add_all([
            AIModel(
                model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
                provider="synthetic", status="active",
            ),
            AISceneRoute(scene=SCENE_PLATFORM_ADAPTER, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_PLATFORM_ADAPTER, current_version=PLATFORM_ADAPTER_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=PLATFORM_ADAPTER_PROMPT_ID, skill_id=SCENE_PLATFORM_ADAPTER,
                version=PLATFORM_ADAPTER_PROMPT_VERSION, template=PLATFORM_ADAPTER_PROMPT_TEMPLATE,
                variables={"vars": PLATFORM_ADAPTER_PROMPT_VARIABLES},
            ),
        ])
        await session.commit()
    yield factory
    await engine.dispose()


async def test_invoke_platform_adapter_gives_block_decision(session_factory):
    async with session_factory() as session:
        invocation = await gw.invoke(
            session,
            SCENE_PLATFORM_ADAPTER,
            {
                "pws": {"product_space_id": "ps-1", "frozen": True},
                "platform_rules": [{"effect": "blocked", "rule_id": "r-1"}],
                "dynamic_events": [],
            },
        )
    payload = json.loads(invocation.text)
    assert payload["missing"] is False
    assert payload["decision"] == "block"
    assert payload["gate"] == "pending_review"
    assert invocation.provider == "synthetic"


async def test_invoke_platform_adapter_missing_pws_does_not_fabricate(session_factory):
    # 无 frozen PWS：synthetic 构造器返回 missing、不造假数据，调用不报错。
    async with session_factory() as session:
        invocation = await gw.invoke(
            session,
            SCENE_PLATFORM_ADAPTER,
            {"pws": {"product_space_id": "ps-1", "frozen": False}, "platform_rules": [], "dynamic_events": []},
        )
    assert json.loads(invocation.text) == {"missing": True, "reason": "no_frozen_pws"}
