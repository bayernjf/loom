"""P4 集成测试：ARTICLE-GEN 文章生成（段12 内容生成，Q116 口径）。

create_all 不跑迁移种子；synthetic 模型 / ARTICLE-GEN 场景路由 / Prompt v0.1
由本文件 helper 自插；FCW 关联包（PWS/三包/PCP/CCR）不造——_assemble_materials
对缺失包容错（返回空），用于锁定"只读消费、不重决策"的最小闭环。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_REVIEW, ContentProduct
from app.core.db import Base, get_session
from app.core.model_registry import drivers
from app.core.model_registry.drivers import GenerationResult
from app.core.model_registry.models import (
    AIModel,
    AISceneRoute,
    SkillPrompt,
    SkillPromptVersion,
)
from app.core.model_registry.seeds import (
    ARTICLE_GEN_PROMPT_ID,
    ARTICLE_GEN_PROMPT_TEMPLATE,
    ARTICLE_GEN_PROMPT_VARIABLES,
    ARTICLE_GEN_PROMPT_VERSION,
    SCENE_ARTICLE_GEN,
    SYNTHETIC_MODEL_ID,
)
from app.core.skill7.models import SkillRun
from app.final.final_whitelist.models import FinalContentWhitelist
from app.main import app

OPS = {"id": "ops-1", "roles": ["operations"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


def _fcw(final_id: str = "fcw-1") -> FinalContentWhitelist:
    return FinalContentWhitelist(
        final_id=final_id,
        tenant_id="t1",
        product_space_id="ps-1",
        pws_id="pws-1",
        pwc_id="pwc-1",
        pcp_id="pcp-1",
        csp_package_id="csp-1",
        cstp_package_id="cstp-1",
        cep_package_id="cep-1",
        platform="douyin",
        slot_id="slot-1",
        goal="种草",
        guards_passed=True,
        issued_by="ops-1",
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
            AISceneRoute(scene=SCENE_ARTICLE_GEN, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_ARTICLE_GEN, current_version=ARTICLE_GEN_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=ARTICLE_GEN_PROMPT_ID, skill_id=SCENE_ARTICLE_GEN,
                version=ARTICLE_GEN_PROMPT_VERSION, template=ARTICLE_GEN_PROMPT_TEMPLATE,
                variables={"vars": ARTICLE_GEN_PROMPT_VARIABLES},
            ),
            _fcw(),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_generate_happy_path(client, session_factory):
    r = await client.post(
        "/api/content/generate", json={"final_id": "fcw-1", "actor": OPS}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["final_id"] == "fcw-1"
    assert body["status"] == CONTENT_REVIEW
    assert body["kind"] == "article"
    assert body["body"]  # synthetic 占位正文非空

    async with session_factory() as session:
        content = await session.get(ContentProduct, body["content_id"])
        assert content.status == CONTENT_REVIEW
        assert content.tenant_id == "t1" and content.product_space_id == "ps-1"
        runs = (await session.scalars(select(SkillRun))).all()
        assert len(runs) == 1
        assert runs[0].skill_id == SCENE_ARTICLE_GEN
        assert runs[0].model_id == SYNTHETIC_MODEL_ID
        assert runs[0].input_cost is not None


async def test_generate_rbac_and_notfound(client):
    r = await client.post(
        "/api/content/generate", json={"final_id": "fcw-1", "actor": CUSTOMER}
    )
    assert r.status_code == 403

    r = await client.post(
        "/api/content/generate", json={"final_id": "ghost", "actor": OPS}
    )
    assert r.status_code == 404


async def test_generate_video_kind_not_implemented(client):
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "kind": "video", "actor": OPS},
    )
    assert r.status_code == 422


async def test_generate_malformed_output_is_502(client, monkeypatch):
    async def _broken(self, **kwargs):
        return GenerationResult(text="not json", input_tokens=3, output_tokens=4)

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _broken)
    r = await client.post(
        "/api/content/generate", json={"final_id": "fcw-1", "actor": OPS}
    )
    assert r.status_code == 502
