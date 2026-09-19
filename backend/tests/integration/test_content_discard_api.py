"""Q124（Q56-b）集成测试：运营作废骨架回池 + 记难产原因。

口径（02 C1.68，接缝按推荐甲拍板）：
- POST /api/content/{id}/discard 为 operations 动作（客户 roles=[] 403），
  body.reason 必填非空白（1..500，空白 422）；
- 仅 review/revising/rejected 可作废（404 未知、其余态 409），成功后 status=
  discarded、discard_reason 落库、视图/列表回带、审计 content.discarded；
- 作废释放 (final_id, language, kind) 唯一占位：同键可重新生成（新行独立），
  未作废的重复仍 409（service 过滤 + partial unique index 双保险）。

create_all 不跑迁移种子；三场景三件套与语言清单由本文件 fixture 自插。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import (
    CONTENT_DISCARDED,
    CONTENT_DRAFT,
    CONTENT_READY,
    CONTENT_REJECTED,
    CONTENT_REVIEW,
    ContentLanguage,
    ContentProduct,
)
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

OPS = {"id": "ops-1", "roles": ["operations"]}
OPS_Q = {"actor_id": "ops-1", "roles": ["operations"]}
ADMIN_Q = {"actor_id": "admin-1", "roles": ["platform_admin"]}
CUSTOMER = {"id": "cust-1", "roles": []}
CUSTOMER_Q = {"actor_id": "cust-1", "roles": []}
REASON = "连续三版复检不过，骨架方向错误，作废回池重生成。"


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


async def _discard(client, cid: str, reason=REASON, actor=OPS):
    return await client.post(
        f"/api/content/{cid}/discard", json={"reason": reason, "actor": actor}
    )


async def test_discard_from_review_sets_status_reason_and_audit(
    client, session_factory
):
    cid = await _generate(client)
    r = await _discard(client, cid)
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["status"] == CONTENT_DISCARDED
    assert view["discard_reason"] == REASON

    async with session_factory() as session:
        row = await session.get(ContentProduct, cid)
        assert row.status == CONTENT_DISCARDED
        assert row.discard_reason == REASON
        logs = list(
            (
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == "content.discarded")
                )
            ).all()
        )
        assert len(logs) == 1
        assert logs[0].entity_id == cid
        assert logs[0].actor_roles == ["operations"]
        assert logs[0].detail["reason"] == REASON

    # 列表仍可见作废行（终态只读，客户列表按租户全量），列表项带回原因。
    r = await client.get("/api/content", params={"tenant_id": "t1"})
    items = r.json()
    assert len(items) == 1
    assert items[0]["status"] == CONTENT_DISCARDED
    assert items[0]["discard_reason"] == REASON


async def test_discard_requires_operations_role(client):
    cid = await _generate(client)
    r = await _discard(client, cid, actor=CUSTOMER)
    assert r.status_code == 403, r.text


async def test_discard_unknown_404(client):
    r = await _discard(client, "ghost-id")
    assert r.status_code == 404, r.text


async def test_discard_from_revising_and_rejected(client):
    # revising → discarded
    cid = await _generate(client)
    r = await client.post(f"/api/content/{cid}/revise", json={"actor": CUSTOMER})
    assert r.status_code == 200
    r = await _discard(client, cid)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_DISCARDED

    # 回池后同键重新生成，再走客户驳回 → rejected → discarded
    cid2 = await _generate(client)
    assert cid2 != cid
    r = await client.post(
        f"/api/content/{cid2}/reject",
        json={"reason": "客户不认可方向", "actor": CUSTOMER},
    )
    assert r.status_code == 200
    assert r.json()["status"] == CONTENT_REJECTED
    r = await _discard(client, cid2)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_DISCARDED


async def test_discard_not_allowed_from_ready_and_draft(client, session_factory):
    # ready_for_publish 已进发布，不可作废。
    cid = await _generate(client)
    r = await client.post(f"/api/content/{cid}/approve", json={"actor": CUSTOMER})
    assert r.status_code == 200
    assert r.json()["status"] == CONTENT_READY
    r = await _discard(client, cid)
    assert r.status_code == 409, r.text

    # draft 态（尚未生成骨架）不可作废。
    async with session_factory() as session:
        session.add(
            ContentProduct(
                tenant_id="t1",
                product_space_id="ps-1",
                final_id="fcw-1",
                goal="种草",
                platform="douyin",
                kind="article",
                language="en-US",
                status=CONTENT_DRAFT,
            )
        )
        await session.commit()
    r = await client.get("/api/content", params={"tenant_id": "t1"})
    draft_id = next(
        it["content_id"] for it in r.json() if it["status"] == CONTENT_DRAFT
    )
    r = await _discard(client, draft_id)
    assert r.status_code == 409, r.text


async def test_discard_blank_reason_422(client):
    cid = await _generate(client)
    r = await _discard(client, cid, reason="   ")
    assert r.status_code == 422, r.text
    # 空串由 schema min_length 拦。
    r = await client.post(
        f"/api/content/{cid}/discard", json={"reason": "", "actor": OPS}
    )
    assert r.status_code == 422


async def test_discarded_slot_released_for_regeneration(client, session_factory):
    cid = await _generate(client)
    r = await _discard(client, cid)
    assert r.status_code == 200

    # 同 final+lang+kind 重新生成成功，新行独立、处于 review。
    cid2 = await _generate(client)
    assert cid2 != cid
    async with session_factory() as session:
        old = await session.get(ContentProduct, cid)
        new = await session.get(ContentProduct, cid2)
        assert old.status == CONTENT_DISCARDED
        assert new.status == CONTENT_REVIEW
        rows = list(
            (
                await session.scalars(
                    select(ContentProduct).where(
                        ContentProduct.final_id == "fcw-1",
                        ContentProduct.language == "zh-CN",
                        ContentProduct.kind == "article",
                    )
                )
            ).all()
        )
        assert len(rows) == 2

    # 新行未作废时，同键第三次生成仍 409（占位仍生效）。
    r = await client.post(
        "/api/content/generate",
        json={"final_id": "fcw-1", "language": "zh-CN", "actor": OPS},
    )
    assert r.status_code == 409, r.text


def _raw_product(final_id: str, tenant_id: str, status: str, **kw) -> ContentProduct:
    return ContentProduct(
        tenant_id=tenant_id,
        product_space_id="ps-1",
        final_id=final_id,
        goal="种草",
        platform="douyin",
        kind="article",
        language="zh-CN",
        status=status,
        **kw,
    )


async def test_needs_attention_queue_filters_order_and_role_gate(
    client, session_factory
):
    # c1 生成后停 review（t1）；c2 approve 后 ready，不进待处置。
    c1 = await _generate(client)
    c2 = await _generate(client, "en-US")
    r = await client.post(f"/api/content/{c2}/approve", json={"actor": CUSTOMER})
    assert r.status_code == 200

    async with session_factory() as session:
        session.add_all([
            _raw_product("fcw-x", "t2", CONTENT_REJECTED, reject_reason="客户驳回"),
            _raw_product("fcw-y", "t1", CONTENT_DISCARDED, discard_reason="已作废"),
            _raw_product("fcw-z", "t1", CONTENT_DRAFT),
        ])
        await session.commit()

    # 缺 actor 422、客户 403、platform_admin/operations 可读。
    r = await client.get("/api/admin/content/needs-attention")
    assert r.status_code == 422, r.text
    r = await client.get("/api/admin/content/needs-attention", params=CUSTOMER_Q)
    assert r.status_code == 403, r.text
    r = await client.get("/api/admin/content/needs-attention", params=ADMIN_Q)
    assert r.status_code == 200, r.text

    r = await client.get("/api/admin/content/needs-attention", params=OPS_Q)
    assert r.status_code == 200, r.text
    items = r.json()
    statuses = {(it["content_id"], it["status"]) for it in items}
    assert (c1, "review") in statuses
    assert any(it["tenant_id"] == "t2" and it["status"] == "rejected" for it in items)
    assert c2 not in {it["content_id"] for it in items}  # ready 不在
    assert all(
        it["status"] in {"review", "revising", "rejected"} for it in items
    )
    assert all("body" not in it for it in items)
    # created_at 升序：API 先造的 c1 排首位。
    assert items[0]["content_id"] == c1


async def test_discarded_is_terminal(client):
    # 作废后客户审阅动作全部失效（终态只读）：approve/reject 状态迁移拒绝 409；
    # revise 先过重生成上限闸（ContentReviseCap）返回 422，同为拒绝语义。
    cid = await _generate(client)
    await _discard(client, cid)
    r = await client.post(f"/api/content/{cid}/approve", json={"actor": CUSTOMER})
    assert r.status_code == 409, r.text
    r = await client.post(
        f"/api/content/{cid}/reject", json={"reason": "x", "actor": CUSTOMER}
    )
    assert r.status_code == 409, r.text
    r = await client.post(f"/api/content/{cid}/revise", json={"actor": CUSTOMER})
    assert r.status_code == 422, r.text
    # 重复作废同样 409。
    r = await _discard(client, cid)
    assert r.status_code == 409
