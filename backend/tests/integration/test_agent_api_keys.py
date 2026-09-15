"""Q88 集成测试：入站一 Agent 一 Key 治理 + 验签。

口径（02 C1.32）：明文仅签发返回一次；DB 存 SHA-256（不存明文/可逆密文）；
platform_admin 红线；吊销 append-only；未知/吊销凭证验签 None；Key 不绑租户。
create_all 不跑迁移（0019 由 PG 一次性容器实测）。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.actor import Actor
from app.core.api_keys import service
from app.core.api_keys.models import AgentApiKey
from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.rbac import PermissionDenied
from app.main import app

PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
OPS = {"id": "ops-1", "roles": ["operations"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _actor(payload) -> Actor:
    return Actor(**payload)


async def _issue(session_factory, name="agent-A", actor=PLATFORM_ADMIN):
    async with session_factory() as session:
        row, secret = await service.issue_key(session, name, _actor(actor))
        await session.commit()
        return row.key_id, secret


# ---------- 纯函数 ----------

def test_generate_key_shape_and_uniqueness():
    secrets = set()
    for _ in range(20):
        plaintext, digest, prefix = service.generate_key()
        secrets.add(plaintext)
        assert plaintext.startswith("loom_")
        assert digest == service.hash_key(plaintext)
        assert len(digest) == 64
        assert plaintext.startswith(prefix)
    assert len(secrets) == 20


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, None),
        ("", None),
        ("Basic abc", None),
        ("Bearer", None),
        ("Bearer  abc123 ", "abc123"),
        ("Bearer abc123", "abc123"),
    ],
)
def test_parse_bearer(header, expected):
    assert service.parse_bearer(header) == expected


# ---------- 服务层 ----------

async def test_issue_stores_only_hash_not_plaintext(session_factory):
    key_id, secret = await _issue(session_factory)
    async with session_factory() as session:
        row = await session.get(AgentApiKey, key_id)
        assert row.status == "active"
        assert row.key_hash == service.hash_key(secret)
        assert secret not in row.key_prefix
        assert row.key_prefix.startswith("loom_")
        assert row.created_by == "pa-1"


async def test_issue_rbac_denied(session_factory):
    for actor in (OPS, CUSTOMER):
        async with session_factory() as session:
            with pytest.raises(PermissionDenied):
                await service.issue_key(session, "x", _actor(actor))


async def test_issue_empty_name_rejected(session_factory):
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await service.issue_key(session, "   ", _actor(PLATFORM_ADMIN))


async def test_verify_active_unknown_and_revoked(session_factory):
    _, secret = await _issue(session_factory)
    async with session_factory() as session:
        row = await service.verify_key(session, secret)
        assert row is not None and row.last_used_at is not None
        assert await service.verify_key(session, "wrong-secret") is None
        assert await service.verify_key(session, "") is None
        await session.commit()

    key_id, secret_b = await _issue(session_factory, name="agent-B")
    async with session_factory() as session:
        revoked = await service.revoke_key(session, key_id, _actor(PLATFORM_ADMIN))
        assert revoked.status == "revoked"
        # 重复吊销幂等，不产生第二条历史。
        again = await service.revoke_key(session, key_id, _actor(PLATFORM_ADMIN))
        assert again is revoked
        await session.commit()

    async with session_factory() as session:
        assert await service.verify_key(session, secret_b) is None


async def test_revoke_keeps_append_only_history_and_audits(session_factory):
    key_id, _ = await _issue(session_factory, name="agent-C")
    async with session_factory() as session:
        await service.revoke_key(session, key_id, _actor(PLATFORM_ADMIN))
        await session.commit()
    async with session_factory() as session:
        rows = (await session.scalars(
            select(AgentApiKey).where(AgentApiKey.key_id == key_id)
        )).all()
        assert len(rows) == 1 and rows[0].status == "revoked"
        assert rows[0].revoked_by == "pa-1" and rows[0].revoked_at is not None
        actions = set((await session.scalars(
            select(AuditLog.action).where(AuditLog.entity_id == key_id)
        )).all())
        assert actions == {"agent_api_key.issue", "agent_api_key.revoke"}


async def test_revoke_rbac_and_not_found(session_factory):
    key_id, _ = await _issue(session_factory)
    async with session_factory() as session:
        with pytest.raises(PermissionDenied):
            await service.revoke_key(session, key_id, _actor(OPS))
        with pytest.raises(service.AgentKeyNotFound):
            await service.revoke_key(session, "missing-id", _actor(PLATFORM_ADMIN))


async def test_list_default_hides_revoked(session_factory):
    key_id, _ = await _issue(session_factory, name="agent-D")
    await _issue(session_factory, name="agent-E")
    async with session_factory() as session:
        await service.revoke_key(session, key_id, _actor(PLATFORM_ADMIN))
        await session.commit()
    async with session_factory() as session:
        active = await service.list_keys(session)
        all_rows = await service.list_keys(session, include_revoked=True)
        assert {r.status for r in active} == {"active"}
        assert len(all_rows) == 2


# ---------- HTTP 治理端点 ----------

async def test_http_issue_secret_once_then_list_masks(client):
    resp = await client.post(
        "/api/admin/agent-keys", json={"name": "agent-F", "actor": PLATFORM_ADMIN}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["secret"].startswith("loom_")
    assert body["status"] == "active"
    key_id = body["key_id"]

    listed = await client.get("/api/admin/agent-keys")
    assert listed.status_code == 200
    first = next(r for r in listed.json() if r["key_id"] == key_id)
    assert "secret" not in first and first["key_prefix"].startswith("loom_")

    again = await client.post(
        "/api/admin/agent-keys", json={"name": "agent-F", "actor": PLATFORM_ADMIN}
    )
    assert again.status_code == 201 and again.json()["secret"] != body["secret"]


async def test_http_issue_rbac_and_validation(client):
    for actor in (OPS, CUSTOMER):
        resp = await client.post(
            "/api/admin/agent-keys", json={"name": "x", "actor": actor}
        )
        assert resp.status_code == 403
    resp = await client.post(
        "/api/admin/agent-keys", json={"name": " ", "actor": PLATFORM_ADMIN}
    )
    assert resp.status_code == 422


async def test_http_revoke_flow_404_and_list_flag(client):
    issued = await client.post(
        "/api/admin/agent-keys", json={"name": "agent-G", "actor": PLATFORM_ADMIN}
    )
    key_id = issued.json()["key_id"]

    denied = await client.post(
        f"/api/admin/agent-keys/{key_id}/revoke", json={"actor": OPS}
    )
    assert denied.status_code == 403

    ok = await client.post(
        f"/api/admin/agent-keys/{key_id}/revoke", json={"actor": PLATFORM_ADMIN}
    )
    assert ok.status_code == 200 and ok.json()["status"] == "revoked"

    missing = await client.post(
        "/api/admin/agent-keys/nope/revoke", json={"actor": PLATFORM_ADMIN}
    )
    assert missing.status_code == 404

    hidden = await client.get("/api/admin/agent-keys")
    assert all(r["key_id"] != key_id for r in hidden.json())
    shown = await client.get(
        "/api/admin/agent-keys", params={"include_revoked": True}
    )
    assert any(r["key_id"] == key_id for r in shown.json())
