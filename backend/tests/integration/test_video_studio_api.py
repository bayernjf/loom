"""Q336 段12 video-studio：分段编目实体（①甲）＋原片留档登记（③甲）集成测试。

钉四件事：
- 读口 operations/platform_admin query actor（缺 actor 422／客户角色 403）；
- 写口（分段 create/update）走 require_internal_actor，无令牌 401、角色不足 403；
- 分段编辑只改元数据不动 content.body，改 text 标 needs_regen 并随响应回带
  屏4 CCR 复检结果（advisory）；全审计（video_segment.create/update）；
- 原片留档：S3 未配置（LOOM_S3_ENDPOINT_URL 空）时上传/下载 503，
  登记表 list 口径不依赖 S3。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import ContentProduct
from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from tests.integration.staff_tokens import acting_as, bearer, issue_staff_token

OPS_ROLES = ["operations"]


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
    app.dependency_overrides[get_auth_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        secret = await issue_staff_token(ac, OPS_ROLES, staff_id="s-vs")
        ac.headers.update(bearer(secret))
        yield ac


async def _seed_content(factory, content_id: str = "c-vs1") -> None:
    async with factory() as session:
        session.add(
            ContentProduct(
                content_id=content_id,
                tenant_id="t1",
                product_space_id="ps-1",
                final_id="fcw-1",
                goal="种草",
                platform="douyin",
                kind="video",
                body="ref://video/abc",
            )
        )
        await session.commit()


def _read_params():
    return [("actor_id", "ops-1"), ("roles", "operations")]


async def test_segment_create_list_and_audit(client, session_factory):
    await _seed_content(session_factory)
    r = await client.post(
        "/api/admin/content/c-vs1/video-segments",
        json={"type": "hook", "text": "首句钩子", "actor": {"id": "x", "roles": []}},
    )
    assert r.status_code == 201, r.text
    seg = r.json()
    assert seg["seq"] == 1 and seg["type"] == "hook" and seg["text"] == "首句钩子"
    assert seg["created_by"] == "s-vs"  # 人员来自凭证，不是 body.actor

    r = await client.get(
        "/api/admin/content/c-vs1/video-segments", params=_read_params()
    )
    assert r.status_code == 200, r.text
    assert [row["segment_id"] for row in r.json()] == [seg["segment_id"]]

    async with session_factory() as session:
        audits = list(
            (
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == "video_segment.create")
                )
            ).all()
        )
        assert len(audits) == 1 and audits[0].actor_id == "s-vs"


async def test_segment_update_metadata_no_regen_text_flags_regen(client, session_factory):
    await _seed_content(session_factory)
    r = await client.post(
        "/api/admin/content/c-vs1/video-segments",
        json={"text": "原句", "actor": {"id": "x", "roles": []}},
    )
    seg_id = r.json()["segment_id"]

    # 元数据编辑：不动 text，不标 needs_regen；随响应回带屏4 CCR 复检（advisory）
    r = await client.put(
        f"/api/admin/video-segments/{seg_id}",
        json={"start_ms": 0, "end_ms": 1500, "type": "intro", "actor": {"id": "x", "roles": []}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["start_ms"] == 0 and body["end_ms"] == 1500 and body["type"] == "intro"
    assert body["needs_regen"] is False
    assert body["script_recheck"]["content_id"] == "c-vs1"

    # 改 text：落新文本并标 needs_regen（重生成走既有链路，不在本口触发）
    r = await client.put(
        f"/api/admin/video-segments/{seg_id}",
        json={"text": "改写后的句子", "actor": {"id": "x", "roles": []}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "改写后的句子" and body["needs_regen"] is True

    async with session_factory() as session:
        audits = list(
            (
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == "video_segment.update")
                )
            ).all()
        )
        assert len(audits) == 2
        assert audits[1].detail["needs_regen"] is True


async def test_segment_write_gate_and_validation(client, session_factory):
    await _seed_content(session_factory)
    # 无令牌 401（直接摘 Authorization 头）
    saved = client.headers.pop("Authorization", None)
    try:
        r = await client.post(
            "/api/admin/content/c-vs1/video-segments",
            json={"text": "x", "actor": {"id": "a", "roles": ["operations"]}},
        )
        assert r.status_code == 401
    finally:
        if saved:
            client.headers.update({"Authorization": saved})
    # 角色不足 403（内部但非 operations 的角色）
    async with acting_as(client, ["product_reviewer"]):
        r = await client.post(
            "/api/admin/content/c-vs1/video-segments",
            json={"text": "x", "actor": {"id": "a", "roles": ["operations"]}},
        )
        assert r.status_code == 403
    # 未知 type / 空文本 422
    r = await client.post(
        "/api/admin/content/c-vs1/video-segments",
        json={"type": "nope", "text": "x", "actor": {"id": "a", "roles": []}},
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/admin/content/c-vs1/video-segments",
        json={"text": "   ", "actor": {"id": "a", "roles": []}},
    )
    assert r.status_code == 422
    # 内容不存在 404
    r = await client.post(
        "/api/admin/content/c-none/video-segments",
        json={"text": "x", "actor": {"id": "a", "roles": []}},
    )
    assert r.status_code == 404
    r = await client.put(
        "/api/admin/video-segments/seg-none",
        json={"seq": 2, "actor": {"id": "a", "roles": []}},
    )
    assert r.status_code == 404


async def test_segment_read_rbac(client, session_factory):
    await _seed_content(session_factory)
    r = await client.get("/api/admin/content/c-vs1/video-segments")
    assert r.status_code == 422  # 缺 actor_id
    r = await client.get(
        "/api/admin/content/c-vs1/video-segments",
        params=[("actor_id", "c-1"), ("roles", "customer")],
    )
    assert r.status_code == 403
    # platform_admin 也可读（管理端跨租户口径）
    r = await client.get(
        "/api/admin/content/c-vs1/video-segments",
        params=[("actor_id", "pa-1"), ("roles", "platform_admin")],
    )
    assert r.status_code == 200


async def test_object_storage_unconfigured_503_and_list(client, session_factory):
    await _seed_content(session_factory)
    # 上传：S3 未配置 → 503（不产生登记行）
    r = await client.post(
        "/api/admin/content/c-vs1/video-objects",
        params=_read_params(),
        files={"file": ("clip.mp4", b"fake-bytes", "video/mp4")},
    )
    assert r.status_code == 503, r.text
    # 列表：登记表口径，不依赖 S3
    r = await client.get("/api/admin/content/c-vs1/video-objects", params=_read_params())
    assert r.status_code == 200 and r.json() == []
    # 下载：未知 object 404
    r = await client.get("/api/admin/video-objects/obj-none/stream", params=_read_params())
    assert r.status_code == 404


async def test_object_register_service_audit(client, session_factory):
    """登记表 service 口径（③甲：对象本体在 S3，本表只登记 key/大小/来源）。"""
    await _seed_content(session_factory)
    from app.content.video_studio import service as vs_service
    from app.core.actor import Actor

    async with session_factory() as session:
        obj = await vs_service.register_object(
            session,
            content_id="c-vs1",
            tenant_id="t1",
            bucket="loom-videos",
            object_key="originals/c-vs1/clip.mp4",
            size_bytes=1234,
            content_type="video/mp4",
            source="agnes",
            actor=Actor(id="ops-1", roles=["operations"]),
        )
        await session.commit()
        rows = await vs_service.list_objects(session, "c-vs1")
        assert [row.object_id for row in rows] == [obj.object_id]
        audits = list(
            (
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == "video_object.register")
                )
            ).all()
        )
        assert len(audits) == 1 and audits[0].detail["bucket"] == "loom-videos"
