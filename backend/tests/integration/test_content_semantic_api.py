"""Q121/Q59 段12 语义级复检集成测试：ARTICLE-SEMANTIC-CHECK 真检测落 review_hits、
命中不阻断客户通过（纯 advisory）、检测不可用不阻断生成、重生成重跑复检。

create_all 不跑迁移种子；synthetic 模型 / ARTICLE-GEN / ARTICLE-QC /
ARTICLE-SEMANTIC-CHECK 场景路由 / Prompt v0.1 / zh-CN 语言由本文件 fixture 自插。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content import service as content_service
from app.content.models import (
    CONTENT_READY,
    CONTENT_REVIEW,
    ContentLanguage,
    ContentProduct,
)
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
    ARTICLE_SEMANTIC_PROMPT_ID,
    ARTICLE_SEMANTIC_PROMPT_TEMPLATE,
    ARTICLE_SEMANTIC_PROMPT_VARIABLES,
    ARTICLE_SEMANTIC_PROMPT_VERSION,
    SCENE_ARTICLE_GEN,
    SCENE_ARTICLE_QC,
    SCENE_ARTICLE_SEMANTIC,
    SYNTHETIC_MODEL_ID,
)
from app.core.skill7.models import SkillRun
from app.final.final_whitelist.models import FinalContentWhitelist
from app.main import app

OPS = {"id": "ops-1", "roles": ["operations"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


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


def _scene_triplet(scene: str, version: str, prompt_id: str, template: str, variables: list):
    return [
        AISceneRoute(scene=scene, model_id=SYNTHETIC_MODEL_ID),
        SkillPrompt(skill_id=scene, current_version=version),
        SkillPromptVersion(
            version_id=prompt_id,
            skill_id=scene,
            version=version,
            template=template,
            variables={"vars": variables},
        ),
    ]


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
        rows = [
            AIModel(
                model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
                provider="synthetic", status="active",
            ),
            *_scene_triplet(
                SCENE_ARTICLE_GEN, ARTICLE_GEN_PROMPT_VERSION,
                ARTICLE_GEN_PROMPT_ID, ARTICLE_GEN_PROMPT_TEMPLATE,
                ARTICLE_GEN_PROMPT_VARIABLES,
            ),
            *_scene_triplet(
                SCENE_ARTICLE_QC, ARTICLE_QC_PROMPT_VERSION,
                ARTICLE_QC_PROMPT_ID, ARTICLE_QC_PROMPT_TEMPLATE,
                ARTICLE_QC_PROMPT_VARIABLES,
            ),
            *_scene_triplet(
                SCENE_ARTICLE_SEMANTIC, ARTICLE_SEMANTIC_PROMPT_VERSION,
                ARTICLE_SEMANTIC_PROMPT_ID, ARTICLE_SEMANTIC_PROMPT_TEMPLATE,
                ARTICLE_SEMANTIC_PROMPT_VARIABLES,
            ),
            ContentLanguage(code="zh-CN", name="简体中文", markets=[], status="active"),
            _fcw(),
        ]
        session.add_all(rows)
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_generation_runs_semantic_check(client, session_factory):
    r = await client.post(
        "/api/content/generate", json={"final_id": "fcw-1", "actor": OPS}
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == CONTENT_REVIEW
    # 词库复检段 + 语义复检段共存；synthetic 正常正文无发现。
    assert set(data["review_hits"]) == {"bans", "downgrades", "block_required", "semantic"}
    assert data["review_hits"]["semantic"] == {"checked": True, "findings": []}

    async with session_factory() as session:
        runs = {r.skill_id for r in (await session.scalars(select(SkillRun))).all()}
    # 一次生成 = ARTICLE-GEN + ARTICLE-QC + ARTICLE-SEMANTIC-CHECK 各一条 SkillRun。
    assert runs == {SCENE_ARTICLE_GEN, SCENE_ARTICLE_QC, SCENE_ARTICLE_SEMANTIC}


async def test_semantic_findings_do_not_block_approve(client, session_factory):
    # 直接造一篇 review 态、正文带语义风险哨兵的成品，跑复检后客户仍可通过（advisory）。
    async with session_factory() as session:
        cp = ContentProduct(
            content_id="cp-risk",
            tenant_id="t1",
            product_space_id="ps-1",
            final_id="fcw-1",
            goal="种草",
            platform="douyin",
            slot_id="slot-1",
            kind="article",
            language="zh-CN",
            body="synthetic [SEMANTIC_RISK] placeholder body",
            review_hits={},
            status=CONTENT_REVIEW,
            created_by="ops-1",
        )
        session.add(cp)
        await session.flush()
        review_hits = await content_service.run_content_review(session, cp)
        await session.commit()
        assert review_hits["semantic"]["checked"] is True
        assert len(review_hits["semantic"]["findings"]) == 1
        assert review_hits["semantic"]["findings"][0]["code"] == "unsubstantiated_claim"
        # advisory：语义命中不抬 block_required（词库 ban 的硬阻断不受影响）。
        assert review_hits["block_required"] is False

    r = await client.post("/api/content/cp-risk/approve?tenant_id=t1", json={"actor": CUSTOMER})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_READY


async def test_semantic_unavailable_does_not_block_generation(
    client, session_factory, monkeypatch
):
    # ARTICLE-GEN/QC 正常、ARTICLE-SEMANTIC-CHECK 抛 ModelConfigError：
    # 成品仍进 review，语义段记 checked=false + error。
    original = gw.invoke

    async def fake_invoke(session, scene, variables):
        if scene == SCENE_ARTICLE_SEMANTIC:
            raise ModelConfigError("semantic route missing")
        return await original(session, scene, variables)

    monkeypatch.setattr(gw, "invoke", fake_invoke)

    r = await client.post(
        "/api/content/generate", json={"final_id": "fcw-1", "actor": OPS}
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == CONTENT_REVIEW
    assert data["review_hits"]["semantic"] == {
        "checked": False,
        "findings": [],
        "error": "ModelConfigError",
    }

    async with session_factory() as session:
        semantic_runs = (
            await session.scalars(
                select(SkillRun).where(SkillRun.skill_id == SCENE_ARTICLE_SEMANTIC)
            )
        ).all()
    assert semantic_runs == []  # 网关不可用不落 SkillRun

    # 检测不可用同样不阻断客户通过。
    r = await client.post(
        f"/api/content/{data['content_id']}/approve?tenant_id=t1", json={"actor": CUSTOMER}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_READY


async def test_regenerate_reruns_semantic_check(client, session_factory):
    r = await client.post(
        "/api/content/generate", json={"final_id": "fcw-1", "actor": OPS}
    )
    assert r.status_code == 201, r.text
    cid = r.json()["content_id"]

    r = await client.post(f"/api/content/{cid}/revise?tenant_id=t1", json={"actor": OPS})
    assert r.status_code == 200 and r.json()["status"] == "revising"
    r = await client.post(f"/api/content/{cid}/regenerate", json={"actor": OPS})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_REVIEW

    async with session_factory() as session:
        semantic_runs = (
            await session.scalars(
                select(SkillRun).where(SkillRun.skill_id == SCENE_ARTICLE_SEMANTIC)
            )
        ).all()
    # 首次生成 + 改稿重生成各跑一次语义复检（Q59 改稿强制重过复检）。
    assert len(semantic_runs) == 2
