"""Q120/Q57 段12 AI 质量分集成测试：ARTICLE-QC 真打分落库、低分不阻断发证、
QC 不可用不阻断生成、重生成上限 content.regen_limit 配置化。

create_all 不跑迁移种子；synthetic 模型 / ARTICLE-GEN 与 ARTICLE-QC 场景路由 /
Prompt v0.1 / zh-CN 语言由本文件 fixture 自插。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content import quality as quality_mod
from app.content.models import (
    CONTENT_READY,
    CONTENT_REVIEW,
    ContentLanguage,
    ContentProduct,
)
from app.core.config_center.cache import config_cache
from app.core.db import Base, get_session
from app.core.model_registry import gateway as gw
from app.core.model_registry.gateway import ModelConfigError
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
    ARTICLE_QC_PROMPT_ID,
    ARTICLE_QC_PROMPT_TEMPLATE,
    ARTICLE_QC_PROMPT_VARIABLES,
    ARTICLE_QC_PROMPT_VERSION,
    SCENE_ARTICLE_GEN,
    SCENE_ARTICLE_QC,
    SYNTHETIC_MODEL_ID,
)
from app.core.skill7.models import SkillRun
from app.final.final_whitelist.models import FinalContentWhitelist
from app.main import app

OPS = {"id": "ops-1", "roles": ["operations"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


@pytest.fixture(autouse=True)
def _reset_config_cache():
    # 配置缓存为进程级单例；本文件任何 knob 覆写在用例后回落种子默认，避免污染它文件。
    yield
    config_cache.invalidate()


def _fcw() -> FinalContentWhitelist:
    return FinalContentWhitelist(
        final_id="fcw-1",
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
            AISceneRoute(scene=SCENE_ARTICLE_QC, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_ARTICLE_QC, current_version=ARTICLE_QC_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=ARTICLE_QC_PROMPT_ID, skill_id=SCENE_ARTICLE_QC,
                version=ARTICLE_QC_PROMPT_VERSION, template=ARTICLE_QC_PROMPT_TEMPLATE,
                variables={"vars": ARTICLE_QC_PROMPT_VARIABLES},
            ),
            ContentLanguage(code="zh-CN", name="简体中文", markets=[], status="active"),
            _fcw(),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_generate_assigns_quality_score(client, session_factory):
    r = await client.post("/api/content/generate", json={
        "final_id": "fcw-1", "kind": "article", "actor": OPS,
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "review"
    assert data["quality_score"] == 0.92
    assert data["quality_issues"] == []
    assert data["quality_threshold"] == 0.85
    assert data["quality_advisory"] is False

    async with session_factory() as session:
        runs = (
            await session.scalars(
                select(SkillRun).where(SkillRun.skill_id == SCENE_ARTICLE_QC)
            )
        ).all()
    assert len(runs) == 1
    assert runs[0].status == "succeeded"
    assert runs[0].source == "llm_auto"
    assert runs[0].wf_id == "WF-10"
    assert runs[0].output_payload["score"] == 0.92


async def test_low_score_does_not_block_approve(client, session_factory):
    # 直接造一篇 review 态、正文带低分哨兵的成品，跑 QC 后客户仍可通过（advisory 不阻断）。
    async with session_factory() as session:
        cp = ContentProduct(
            content_id="cp-low",
            tenant_id="t1",
            product_space_id="ps-1",
            final_id="fcw-1",
            goal="种草",
            platform="douyin",
            slot_id="slot-1",
            kind="article",
            language="zh-CN",
            body="synthetic [LOW_QC] placeholder body",
            review_hits={},
            status=CONTENT_REVIEW,
            created_by="ops-1",
        )
        session.add(cp)
        await quality_mod.invoke_article_qc(session, cp)
        await session.commit()
        assert cp.quality_score == 0.62

    r = await client.post("/api/content/cp-low/approve", json={"actor": CUSTOMER})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == CONTENT_READY
    assert data["quality_score"] == 0.62
    assert data["quality_advisory"] is True  # 低分仅提示，客户 Gate 仍可放行


async def test_qc_unavailable_does_not_block_generation(client, monkeypatch):
    # ARTICLE-GEN 正常、ARTICLE-QC 抛 ModelConfigError：成品仍进 review，分数留空。
    original = gw.invoke

    async def fake_invoke(session, scene, variables):
        if scene == SCENE_ARTICLE_QC:
            raise ModelConfigError("qc route missing")
        return await original(session, scene, variables)

    monkeypatch.setattr(gw, "invoke", fake_invoke)

    r = await client.post("/api/content/generate", json={
        "final_id": "fcw-1", "kind": "article", "actor": OPS,
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "review"
    assert data["quality_score"] is None
    assert data["quality_issues"] == [{"qc_error": "ModelConfigError"}]
    assert data["quality_advisory"] is None


async def test_regen_limit_is_configurable(client, session_factory):
    # 运营把 content.regen_limit 调到 1：首次改稿重生成后不可再改稿（Q56 转人工）。
    config_cache.apply({"content.regen_limit": 1})

    r = await client.post("/api/content/generate", json={
        "final_id": "fcw-1", "kind": "article", "actor": OPS,
    })
    assert r.status_code == 201, r.text
    cid = r.json()["content_id"]

    r = await client.post(f"/api/content/{cid}/revise", json={"actor": OPS})
    assert r.status_code == 200 and r.json()["status"] == "revising"

    r = await client.post(f"/api/content/{cid}/regenerate", json={"actor": OPS})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "review"
    assert r.json()["regenerate_count"] == 1

    r = await client.post(f"/api/content/{cid}/revise", json={"actor": OPS})
    assert r.status_code == 422
    assert "1/1" in r.json()["detail"]
