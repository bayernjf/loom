"""Q122 集成测试：客户内容页只读列表/详情 + Q56-a 人工编辑正文。

口径（02 C1.66，接缝按推荐甲拍板）：
- GET /api/content?tenant_id= 与 GET /api/content/{id} 为客户只读口，无 query actor 闸
  （同 Q101 compliance/overview），列表项不带 body；
- PATCH /api/content/{id}/body 为客户口径（roles 恒空可调），仅 revising 态允许，
  提交后重过词库 + 语义复检与 ARTICLE-QC，回 review，不增 regenerate_count；
- 生成 / 重生成仍为 operations（Q116 定稿，本片不改闸）。

create_all 不跑迁移种子；三场景三件套与语言清单由本文件 fixture 自插。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import (
    CONTENT_REVIEW,
    CONTENT_REVISING,
    ContentLanguage,
    ContentProduct,
)
from app.core.compliance_wordlist.models import ComplianceWordlistEntry
from app.core.db import Base, get_session
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
# Q106/Q122：客户前端身份 roles 恒空（server env 自报），客户端点必须可调。
CUSTOMER = {"id": "cust-1", "roles": []}


def _fcw(final_id: str = "fcw-1", tenant_id: str = "t1") -> FinalContentWhitelist:
    return FinalContentWhitelist(
        final_id=final_id,
        tenant_id=tenant_id,
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


def _scene_triplet(session, scene: str, version: str, version_id: str, template: str, variables: list[str]) -> None:
    session.add(AISceneRoute(scene=scene, model_id=SYNTHETIC_MODEL_ID))
    session.add(SkillPrompt(skill_id=scene, current_version=version))
    session.add(
        SkillPromptVersion(
            version_id=version_id,
            skill_id=scene,
            version=version,
            template=template,
            variables={"vars": variables},
        )
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
        session.add(
            AIModel(
                model_id=SYNTHETIC_MODEL_ID,
                model_code="synthetic-deterministic",
                provider="synthetic",
                status="active",
            )
        )
        _scene_triplet(
            session, SCENE_ARTICLE_GEN, ARTICLE_GEN_PROMPT_VERSION,
            ARTICLE_GEN_PROMPT_ID, ARTICLE_GEN_PROMPT_TEMPLATE,
            ARTICLE_GEN_PROMPT_VARIABLES,
        )
        _scene_triplet(
            session, SCENE_ARTICLE_QC, ARTICLE_QC_PROMPT_VERSION,
            ARTICLE_QC_PROMPT_ID, ARTICLE_QC_PROMPT_TEMPLATE,
            ARTICLE_QC_PROMPT_VARIABLES,
        )
        _scene_triplet(
            session, SCENE_ARTICLE_SEMANTIC, ARTICLE_SEMANTIC_PROMPT_VERSION,
            ARTICLE_SEMANTIC_PROMPT_ID, ARTICLE_SEMANTIC_PROMPT_TEMPLATE,
            ARTICLE_SEMANTIC_PROMPT_VARIABLES,
        )
        session.add_all([
            ContentLanguage(code="zh-CN", name="简体中文", markets=[], status="active"),
            ContentLanguage(code="en-US", name="English", markets=[], status="active"),
            _fcw(),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _generate(client, language: str = "zh-CN") -> str:
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "language": language, "actor": OPS},
    )
    assert r.status_code == 201, r.text
    return r.json()["content_id"]


async def test_list_by_tenant_excludes_body_and_unknown_tenant_empty(client):
    await _generate(client, "zh-CN")
    await _generate(client, "en-US")

    r = await client.get("/api/content", params={"tenant_id": "t1"})
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 2
    assert {it["language"] for it in items} == {"zh-CN", "en-US"}
    # 每语言独立成品，均按 final_id 并列；列表项不带正文。
    assert all("body" not in it for it in items)
    assert all(it["final_id"] == "fcw-1" for it in items)
    # 列表项仍带 AI 分与复检提示所需字段。
    assert all("quality_score" in it and "review_hits" in it for it in items)

    r = await client.get("/api/content", params={"tenant_id": "ghost"})
    assert r.status_code == 200
    assert r.json() == []

    r = await client.get("/api/content")
    assert r.status_code == 422


async def test_detail_returns_body_404(client):
    cid = await _generate(client)
    r = await client.get(f"/api/content/{cid}?tenant_id=t1")
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["content_id"] == cid
    assert detail["body"]

    r = await client.get("/api/content/ghost-id?tenant_id=t1")
    assert r.status_code == 404


async def test_manual_edit_happy_path_reruns_reviews_without_regen_count(
    client, session_factory
):
    cid = await _generate(client)
    r = await client.post(f"/api/content/{cid}/revise?tenant_id=t1", json={"actor": CUSTOMER})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_REVISING

    r = await client.patch(
        f"/api/content/{cid}/body?tenant_id=t1",
        json={"body": "这是客户人工改写后的全新正文。", "actor": CUSTOMER},
    )
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["status"] == CONTENT_REVIEW
    assert view["body"] == "这是客户人工改写后的全新正文。"
    # 人工编辑不走 ARTICLE-GEN、不占重生成次数。
    assert view["regenerate_count"] == 0

    async with session_factory() as session:
        content = await session.get(ContentProduct, cid)
        assert content.status == CONTENT_REVIEW
        runs = [r.skill_id for r in (await session.scalars(select(SkillRun))).all()]
    # 首次生成 GEN/QC/SEMANTIC 各 1 条；人工提交重跑 QC + SEMANTIC（GEN 不重跑）。
    assert sorted(runs) == sorted(
        [SCENE_ARTICLE_GEN, SCENE_ARTICLE_QC, SCENE_ARTICLE_QC,
         SCENE_ARTICLE_SEMANTIC, SCENE_ARTICLE_SEMANTIC]
    )


async def test_manual_edit_guards(client):
    cid = await _generate(client)
    # review 态直接编辑 → 409（必须先 revise）。
    r = await client.patch(
        f"/api/content/{cid}/body?tenant_id=t1", json={"body": "x", "actor": CUSTOMER}
    )
    assert r.status_code == 409
    # 空白正文 → 422。
    await client.post(f"/api/content/{cid}/revise?tenant_id=t1", json={"actor": CUSTOMER})
    r = await client.patch(
        f"/api/content/{cid}/body?tenant_id=t1", json={"body": "   ", "actor": CUSTOMER}
    )
    assert r.status_code == 422
    # 不存在 → 404。
    r = await client.patch(
        "/api/content/ghost/body?tenant_id=t1", json={"body": "x", "actor": CUSTOMER}
    )
    assert r.status_code == 404


async def test_manual_edit_reruns_wordlist_and_semantic(
    client, session_factory
):
    cid = await _generate(client)
    await client.post(f"/api/content/{cid}/revise?tenant_id=t1", json={"actor": CUSTOMER})

    # 人工正文同时含词库 ban 词与语义哨兵：词库硬阻断标记抬升、语义发现落段，
    # 但人工提交仍照常回 review（语义纯 advisory；ban 阻断在审阅侧消费，同 generate）。
    async with session_factory() as session:
        session.add(
            ComplianceWordlistEntry(
                word="违禁词", level="high", action="ban", status="active"
            )
        )
        await session.commit()

    r = await client.patch(
        f"/api/content/{cid}/body?tenant_id=t1",
        json={"body": "人工正文包含违禁词与 [SEMANTIC_RISK] 哨兵。", "actor": CUSTOMER},
    )
    assert r.status_code == 200, r.text
    hits = r.json()["review_hits"]
    assert hits["block_required"] is True
    assert any(h["word"] == "违禁词" for h in hits["bans"])
    semantic = hits["semantic"]
    assert semantic["checked"] is True
    assert [f["code"] for f in semantic["findings"]] == ["unsubstantiated_claim"]
    assert r.json()["status"] == CONTENT_REVIEW
