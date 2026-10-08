"""P4 集成测试：VIDEO-GEN 视频生成（段12 内容生成，Q323 载体切片）。

与 test_content_api.py（ARTICLE-GEN）同构：create_all 不跑迁移种子；synthetic
模型 / VIDEO-GEN 场景路由 / Prompt v0.1 由本文件 fixture 自插；FCW 关联包
（PWS/三包/PCP/CCR）不造——_assemble_materials 对缺失包容错。Q323 只落
video_ref 引用字符串载体，不触达真实视频管线；真视频存储/agnes mode 取值未给【待补】。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_READY, CONTENT_REVIEW, ContentLanguage, ContentProduct
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
    SCENE_VIDEO_GEN,
    SYNTHETIC_MODEL_ID,
    VIDEO_GEN_PROMPT_ID,
    VIDEO_GEN_PROMPT_TEMPLATE,
    VIDEO_GEN_PROMPT_VARIABLES,
    VIDEO_GEN_PROMPT_VERSION,
)
from app.core.skill7.models import SkillRun
from app.final.final_whitelist.models import FcwSnapshot, FinalContentWhitelist
from app.main import app
from tests.integration.fcw_rows import add_fcw

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
        await add_fcw(session, [
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
            ContentLanguage(
                code="zh-CN", name="简体中文", markets=[], status="active"
            ),
            _fcw(),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_video_generate_happy_path(client, session_factory):
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "kind": "video", "actor": OPS},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["final_id"] == "fcw-1"
    assert body["status"] == CONTENT_REVIEW
    assert body["kind"] == "video"
    assert body["body"] == "synthetic:video:fcw-1:zh-CN"
    assert body["review_hits"] == {}

    async with session_factory() as session:
        content = await session.get(ContentProduct, body["content_id"])
        assert content.status == CONTENT_REVIEW
        assert content.kind == "video"
        assert content.tenant_id == "t1" and content.product_space_id == "ps-1"
        runs = {r.skill_id: r for r in (await session.scalars(select(SkillRun))).all()}
        # Q323：视频生成只调 VIDEO-GEN 一条（不跑文本复检/ARTICLE-QC）。
        assert set(runs) == {SCENE_VIDEO_GEN}
        assert runs[SCENE_VIDEO_GEN].model_id == SYNTHETIC_MODEL_ID
        assert runs[SCENE_VIDEO_GEN].output_payload == {"video_ref": "synthetic:video:fcw-1:zh-CN"}
        assert runs[SCENE_VIDEO_GEN].input_cost is not None


async def test_video_generate_rbac_and_notfound(client):
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "kind": "video", "actor": CUSTOMER},
    )
    assert r.status_code == 403

    r = await client.post(
        "/api/content/generate",
        json={"final_id": "ghost", "kind": "video", "actor": OPS},
    )
    assert r.status_code == 404


async def test_video_generate_unknown_kind_422(client):
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "kind": "audio", "actor": OPS},
    )
    assert r.status_code == 422


async def test_video_generate_duplicate_409(client):
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "kind": "video", "actor": OPS},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "kind": "video", "actor": OPS},
    )
    assert r.status_code == 409


async def test_video_generate_malformed_output_502(client, monkeypatch):
    async def _broken(self, **kwargs):
        return GenerationResult(text="not json", input_tokens=3, output_tokens=4)

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _broken)
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "kind": "video", "actor": OPS},
    )
    assert r.status_code == 502


async def test_video_generate_revoked_409(session_factory, client):
    # Q251 裁决 b（断消费）：所引 FCW 快照 revoked 立即 409，与 ARTICLE-GEN 同口径。
    async with session_factory() as session:
        session.add(
            FcwSnapshot(
                final_id="fcw-1",
                tenant_id="t1",
                product_space_id="ps-1",
                version="v1",
                status="revoked",
                is_active=False,
                platform="douyin",
                slot_id="slot-1",
                goal="种草",
                country=None,
                snapshot={},
            )
        )
        await session.commit()
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "kind": "video", "actor": OPS},
    )
    assert r.status_code == 409


async def test_video_customer_approve(client):
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "kind": "video", "actor": OPS},
    )
    assert r.status_code == 201, r.text
    cid = r.json()["content_id"]
    r = await client.post(
        f"/api/content/{cid}/approve?tenant_id=t1", json={"actor": CUSTOMER}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_READY
