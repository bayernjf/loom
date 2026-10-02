"""VIDEO-GEN 场景集成测试（V1 引擎预备）：场景路由＋Prompt v0.1 就位后，
gateway.invoke 经 synthetic 驱动返回确定性 video_ref。

create_all 不跑迁移种子；synthetic 模型与 VIDEO-GEN 场景路由/Prompt v0.1
由本文件 fixture 自插。视频载体与业务链路随 video-studio 后续切片。
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
    SCENE_VIDEO_GEN,
    SYNTHETIC_MODEL_ID,
    VIDEO_GEN_PROMPT_ID,
    VIDEO_GEN_PROMPT_TEMPLATE,
    VIDEO_GEN_PROMPT_VARIABLES,
    VIDEO_GEN_PROMPT_VERSION,
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
            AISceneRoute(scene=SCENE_VIDEO_GEN, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_VIDEO_GEN, current_version=VIDEO_GEN_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=VIDEO_GEN_PROMPT_ID, skill_id=SCENE_VIDEO_GEN,
                version=VIDEO_GEN_PROMPT_VERSION, template=VIDEO_GEN_PROMPT_TEMPLATE,
                variables={"vars": VIDEO_GEN_PROMPT_VARIABLES},
            ),
        ])
        await session.commit()
    yield factory
    await engine.dispose()


async def test_invoke_video_gen_returns_ref(session_factory):
    async with session_factory() as session:
        invocation = await gw.invoke(
            session,
            SCENE_VIDEO_GEN,
            {
                "_final_id": "fcw-1",
                "materials": "synthetic FCW material pack",
                "language": "zh-CN",
            },
        )
    payload = json.loads(invocation.text)
    assert payload == {"video_ref": "synthetic:video:fcw-1:zh-CN"}
    assert invocation.provider == "synthetic"


async def test_invoke_video_gen_without_final_id_returns_empty_ref(session_factory):
    # 无 final_id（无可用原料）：synthetic 构造器给空 video_ref，调用不报错。
    async with session_factory() as session:
        invocation = await gw.invoke(
            session,
            SCENE_VIDEO_GEN,
            {"materials": "", "language": "zh-CN"},
        )
    assert json.loads(invocation.text) == {"video_ref": ""}
