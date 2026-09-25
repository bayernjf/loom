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

from app.content.models import (
    CONTENT_READY,
    CONTENT_REJECTED,
    CONTENT_REVIEW,
    CONTENT_REVISING,
    MAX_REGENERATE,
    ContentLanguage,
    ContentProduct,
)
from app.core.compliance_wordlist.models import ComplianceWordlistEntry
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
            AISceneRoute(scene=SCENE_ARTICLE_QC, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_ARTICLE_QC, current_version=ARTICLE_QC_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=ARTICLE_QC_PROMPT_ID, skill_id=SCENE_ARTICLE_QC,
                version=ARTICLE_QC_PROMPT_VERSION, template=ARTICLE_QC_PROMPT_TEMPLATE,
                variables={"vars": ARTICLE_QC_PROMPT_VARIABLES},
            ),
            AISceneRoute(scene=SCENE_ARTICLE_SEMANTIC, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_ARTICLE_SEMANTIC, current_version=ARTICLE_SEMANTIC_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=ARTICLE_SEMANTIC_PROMPT_ID, skill_id=SCENE_ARTICLE_SEMANTIC,
                version=ARTICLE_SEMANTIC_PROMPT_VERSION, template=ARTICLE_SEMANTIC_PROMPT_TEMPLATE,
                variables={"vars": ARTICLE_SEMANTIC_PROMPT_VARIABLES},
            ),
            ContentLanguage(
                code="zh-CN", name="简体中文", markets=[], status="active"
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
        runs = {r.skill_id: r for r in (await session.scalars(select(SkillRun))).all()}
        # 一次生成 = ARTICLE-GEN 写正文 + ARTICLE-QC 质量分（Q120）
        # + ARTICLE-SEMANTIC-CHECK 语义复检（Q121），各一条 SkillRun。
        assert set(runs) == {
            SCENE_ARTICLE_GEN, SCENE_ARTICLE_QC, SCENE_ARTICLE_SEMANTIC,
        }
        assert runs[SCENE_ARTICLE_GEN].model_id == SYNTHETIC_MODEL_ID
        assert runs[SCENE_ARTICLE_GEN].input_cost is not None
        assert runs[SCENE_ARTICLE_QC].output_payload["score"] == 0.92
        assert runs[SCENE_ARTICLE_SEMANTIC].output_payload["findings"] == []


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


async def _generate(client) -> str:
    r = await client.post(
        "/api/content/generate", json={"final_id": "fcw-1", "actor": OPS}
    )
    assert r.status_code == 201, r.text
    return r.json()["content_id"]


async def test_customer_approve(client):
    cid = await _generate(client)
    r = await client.post(f"/api/content/{cid}/approve?tenant_id=t1", json={"actor": CUSTOMER})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_READY


async def test_reject_requires_reason(client):
    cid = await _generate(client)
    r = await client.post(f"/api/content/{cid}/reject?tenant_id=t1", json={"actor": CUSTOMER})
    assert r.status_code == 422
    r = await client.post(
        f"/api/content/{cid}/reject?tenant_id=t1", json={"reason": "不合规", "actor": CUSTOMER}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_REJECTED
    assert r.json()["reject_reason"] == "不合规"


async def test_revise_regenerate_flow(client):
    cid = await _generate(client)
    r = await client.post(f"/api/content/{cid}/revise?tenant_id=t1", json={"actor": CUSTOMER})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_REVISING

    r = await client.post(f"/api/content/{cid}/regenerate", json={"actor": OPS})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_REVIEW
    assert r.json()["regenerate_count"] == 1


async def test_revise_capped_at_max(client):
    cid = await _generate(client)
    for _ in range(MAX_REGENERATE):
        await client.post(f"/api/content/{cid}/revise?tenant_id=t1", json={"actor": CUSTOMER})
        r = await client.post(f"/api/content/{cid}/regenerate", json={"actor": OPS})
        assert r.status_code == 200, r.text
    r = await client.post(f"/api/content/{cid}/revise?tenant_id=t1", json={"actor": CUSTOMER})
    assert r.status_code == 422


async def test_compliance_wordlist_hit(client, session_factory, monkeypatch):
    async with session_factory() as session:
        session.add(
            ComplianceWordlistEntry(
                word="违禁词", level="high", action="ban", status="active",
            )
        )
        await session.commit()
    monkeypatch.setitem(
        synthetic.BUILDERS, SCENE_ARTICLE_GEN,
        lambda variables: {"body": "正文包含违禁词"},
    )
    r = await client.post(
        "/api/content/generate", json={"final_id": "fcw-1", "actor": OPS}
    )
    assert r.status_code == 201, r.text
    hits = r.json()["review_hits"]
    assert hits["block_required"] is True
    assert any(h["word"] == "违禁词" for h in hits["bans"])
