"""Q125（Q60c）集成测试：运营待发布队列 + 平台链接/ID 回填。

口径（02 C1.69，接缝按推荐甲拍板）：
- GET /api/admin/content/ready-to-publish 为 operations 读口（query actor 闸，
  缺 actor 422、客户 403）：跨租户仅返回 ready_for_publish 且 published_at
  为空的成品，created_at 升序（先到先发），行不含 body；
- PUT /api/admin/content/{id}/publish-info 为 operations 写口（客户 403、
  未知 404、非 ready 409、url 空白 422）：回填 url/post_id，published_at 仅
  首次落时间；可重复回填修正 url，post_id 缺省不动已有值；审计
  content.publish_info_set。
- Agent 抓取 / effect-callback / 时序回流随段 13（V2），本切片不涉及。

create_all 不跑迁移种子；三场景三件套与语言清单由本文件 fixture 自插。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_READY, ContentLanguage
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
from app.core.models import AuditLog
from app.final.final_whitelist.models import FinalContentWhitelist
from app.main import app
from tests.integration.fcw_rows import add_fcw

OPS = {"id": "ops-1", "roles": ["operations"]}
OPS_Q = {"actor_id": "ops-1", "roles": ["operations"]}
ADMIN_Q = {"actor_id": "admin-1", "roles": ["platform_admin"]}
CUSTOMER = {"id": "cust-1", "roles": []}
CUSTOMER_Q = {"actor_id": "cust-1", "roles": []}


def _fcw(final_id: str, tenant_id: str) -> FinalContentWhitelist:
    # FCW 唯一约束 (pws_id, pwc_id, platform, slot_id)：两条 FCW 包 id/发布位必须不同。
    suffix = final_id.split("-")[1]
    return FinalContentWhitelist(
        final_id=final_id,
        tenant_id=tenant_id,
        product_space_id=f"ps-{final_id}",
        pws_id=f"pws-{suffix}",
        pwc_id=f"pwc-{suffix}",
        pcp_id=f"pcp-{suffix}",
        csp_package_id=f"csp-{suffix}",
        cstp_package_id=f"cstp-{suffix}",
        cep_package_id=f"cep-{suffix}",
        platform="douyin",
        slot_id=f"slot-{suffix}",
        goal="种草",
        guards_passed=True,
        issued_by="ops-1",
    )


def _scene_triplet(session, scene, version, version_id, template, variables) -> None:
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
        await add_fcw(session, [
            ContentLanguage(code="zh-CN", name="简体中文", markets=[], status="active"),
            ContentLanguage(code="en-US", name="English", markets=[], status="active"),
            _fcw("fcw-1", "t1"),
            _fcw("fcw-2", "t2"),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _norm_ts(value: str) -> str:
    # sqlite 往返丢失 tz 标记（首次响应带 Z、二次读回为 naive），去 Z 后按串比较。
    return value.removesuffix("Z")


async def _generate(client, final_id: str = "fcw-1", language: str = "zh-CN") -> str:
    r = await client.post(
        "/api/content/generate",
        json={"final_id": final_id, "language": language, "actor": OPS},
    )
    assert r.status_code == 201, r.text
    return r.json()["content_id"]


async def _approve(client, cid: str, tenant: str = "t1") -> None:
    r = await client.post(
        f"/api/content/{cid}/approve?tenant_id={tenant}",
        json={"actor": CUSTOMER},
    )
    assert r.status_code == 200, r.text


async def _ready(client, final_id: str = "fcw-1", language: str = "zh-CN") -> str:
    cid = await _generate(client, final_id, language)
    # Q200 #32：成品归属租户（fcw-2 属 t2），approve 声明对应租户。
    await _approve(client, cid, tenant="t2" if final_id == "fcw-2" else "t1")
    return cid


async def test_backfill_happy_path_sets_fields_and_audit(client, session_factory):
    cid = await _ready(client)
    r = await client.put(
        f"/api/admin/content/{cid}/publish-info",
        json={
            "url": "https://www.douyin.com/video/123456",
            "platform_post_id": "123456",
            "actor": OPS,
        },
    )
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["status"] == CONTENT_READY
    assert view["published_url"] == "https://www.douyin.com/video/123456"
    assert view["platform_post_id"] == "123456"
    assert view["published_at"]

    async with session_factory() as session:
        logs = list(
            (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "content.publish_info_set"
                    )
                )
            ).all()
        )
        assert len(logs) == 1
        assert logs[0].entity_id == cid
        assert logs[0].actor_roles == ["operations"]


async def test_backfill_requires_operations_role(client):
    cid = await _ready(client)
    r = await client.put(
        f"/api/admin/content/{cid}/publish-info",
        json={"url": "https://x/1", "actor": CUSTOMER},
    )
    assert r.status_code == 403, r.text


async def test_backfill_unknown_404(client):
    r = await client.put(
        "/api/admin/content/ghost/publish-info",
        json={"url": "https://x/1", "actor": OPS},
    )
    assert r.status_code == 404, r.text


async def test_backfill_only_accepted_in_ready_state(client):
    # review 态（生成后未 approve）→ 409。
    cid = await _generate(client)
    r = await client.put(
        f"/api/admin/content/{cid}/publish-info",
        json={"url": "https://x/1", "actor": OPS},
    )
    assert r.status_code == 409, r.text

    # rejected 态 → 409。
    r = await client.post(
        f"/api/content/{cid}/reject?tenant_id=t1",
        json={"reason": "客户不认可", "actor": CUSTOMER},
    )
    assert r.status_code == 200
    r = await client.put(
        f"/api/admin/content/{cid}/publish-info",
        json={"url": "https://x/1", "actor": OPS},
    )
    assert r.status_code == 409, r.text


async def test_backfill_blank_url_422(client):
    cid = await _ready(client)
    r = await client.put(
        f"/api/admin/content/{cid}/publish-info",
        json={"url": "   ", "actor": OPS},
    )
    assert r.status_code == 422, r.text
    r = await client.put(
        f"/api/admin/content/{cid}/publish-info",
        json={"url": "", "actor": OPS},
    )
    assert r.status_code == 422, r.text


async def test_repeated_backfill_overwrites_url_keeps_timestamp(client):
    cid = await _ready(client)
    r = await client.put(
        f"/api/admin/content/{cid}/publish-info",
        json={"url": "https://x/1", "platform_post_id": "p1", "actor": OPS},
    )
    assert r.status_code == 200
    first_at = r.json()["published_at"]

    # 修正链接：url 覆盖；未带 post_id 时保留原值；published_at 保持首次时间。
    r = await client.put(
        f"/api/admin/content/{cid}/publish-info",
        json={"url": "https://x/2-corrected", "actor": OPS},
    )
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["published_url"] == "https://x/2-corrected"
    assert view["platform_post_id"] == "p1"
    assert _norm_ts(view["published_at"]) == _norm_ts(first_at)

    # 显式空串 post_id 视为清空。
    r = await client.put(
        f"/api/admin/content/{cid}/publish-info",
        json={"url": "https://x/3", "platform_post_id": "", "actor": OPS},
    )
    assert r.status_code == 200
    assert r.json()["platform_post_id"] is None


async def test_ready_queue_cross_tenant_order_and_exclusions(client):
    c1 = await _ready(client, "fcw-1", "zh-CN")  # t1 ready 未回填
    c2 = await _ready(client, "fcw-2", "zh-CN")  # t2 ready 未回填
    # review 态成品不进队列。
    await _generate(client, "fcw-1", "en-US")

    r = await client.get("/api/admin/content/ready-to-publish", params=OPS_Q)
    assert r.status_code == 200, r.text
    items = r.json()
    assert [it["content_id"] for it in items] == [c1, c2]
    # 跨租户、无 body。
    assert {it["tenant_id"] for it in items} == {"t1", "t2"}
    assert all("body" not in it for it in items)
    assert all(it["status"] == CONTENT_READY for it in items)
    assert all(it["published_at"] is None for it in items)

    # 回填 c1 后仍在队列（已回填分区显链接），顺序不变且带回链接。
    r = await client.put(
        f"/api/admin/content/{c1}/publish-info",
        json={"url": "https://x/1", "actor": OPS},
    )
    assert r.status_code == 200
    r = await client.get("/api/admin/content/ready-to-publish", params=OPS_Q)
    items = r.json()
    assert [it["content_id"] for it in items] == [c1, c2]
    by_id = {it["content_id"]: it for it in items}
    assert by_id[c1]["published_url"] == "https://x/1"
    assert by_id[c1]["published_at"]
    assert by_id[c2]["published_at"] is None


async def test_ready_queue_role_gate(client):
    await _ready(client)
    # 缺 actor → 422。
    r = await client.get("/api/admin/content/ready-to-publish")
    assert r.status_code == 422, r.text
    # 客户身份 → 403。
    r = await client.get("/api/admin/content/ready-to-publish", params=CUSTOMER_Q)
    assert r.status_code == 403, r.text
    # review 态不影响空队列口径：全新身份 operations 可见。
    r = await client.get("/api/admin/content/ready-to-publish", params=OPS_Q)
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_ready_queue_readable_by_platform_admin_but_write_denied(client):
    # Q107 同构：读口 operations | platform_admin 双角色；写口 operations 硬闸。
    cid = await _ready(client)
    r = await client.get("/api/admin/content/ready-to-publish", params=ADMIN_Q)
    assert r.status_code == 200, r.text
    assert [it["content_id"] for it in r.json()] == [cid]

    r = await client.put(
        f"/api/admin/content/{cid}/publish-info",
        json={
            "url": "https://x/1",
            "actor": {"id": "admin-1", "roles": ["platform_admin"]},
        },
    )
    assert r.status_code == 403, r.text
