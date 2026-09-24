"""Q178 集成测试：内部运营个人访问令牌（PAT，甲案第一切片）。

覆盖三层：
1. 服务层/纯函数：明文仅一次、只存 SHA-256、角色校验、轮换、吊销、审计；
2. 门控关闭（默认）：治理端点沿用 V1 actor 自报（含引导签发首个 platform_admin 令牌），
   /api/auth/me 返回 400，Q88/Q109 agent-keys GET 仍开放；
3. 门控开启（LOOM_STAFF_AUTH_ENABLED=true）：内部端点无令牌 401、角色不足 403、
   query/body 自报高角色被令牌身份覆盖（防提权）、审计落到真实人员；客户口/公开口/
   机器 Agent 口不受 staff 门控影响。

create_all 不跑迁移（0040 由 PG 一次性容器实测）。门控开有认证/业务两个并发 session，
故用 StaticPool 让内存 SQLite 跨连接共享同一库。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.actor import Actor
from app.core.db import Base, get_session, settings
from app.core.models import AuditLog
from app.core.rbac import INTERNAL_ROLES, PermissionDenied
from app.core.staff_auth import service
from app.core.staff_auth.deps import get_auth_session
from app.core.staff_auth.models import StaffApiKey
from app.main import app

PA = {"id": "pa-self", "roles": ["platform_admin"]}
OPS = {"id": "ops-self", "roles": ["operations"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
        yield ac


def _bearer(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


async def _bootstrap(client, roles, *, staff_id="s-pa", staff_name="Pat Admin"):
    """门控关用自报 platform_admin 经 HTTP 引导签发一枚 staff 令牌，返回 (view, secret)。"""
    resp = await client.post(
        "/api/admin/staff-keys",
        json={
            "staff_id": staff_id,
            "staff_name": staff_name,
            "roles": roles,
            "actor": PA,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body, body["secret"]


# ---------- 纯函数 ----------

def test_generate_staff_key_shape_and_uniqueness():
    seen = set()
    for _ in range(20):
        plaintext, digest, prefix = service.generate_staff_key()
        seen.add(plaintext)
        assert plaintext.startswith("loom_staff_")
        assert digest == service.hash_key(plaintext)
        assert len(digest) == 64
        assert plaintext.startswith(prefix)
        # 与机器 Agent Key（loom_ 前缀）分域。
        assert not plaintext.startswith("loom_agent")
    assert len(seen) == 20
    assert service.is_staff_token("loom_staff_abc") is True
    assert service.is_staff_token("loom_abc") is False
    assert service.is_staff_token(None) is False
    assert INTERNAL_ROLES == {
        "operations",
        "platform_admin",
        "product_reviewer",
        "dictionary_admin",
        "internal_compliance",
    }


@pytest.mark.parametrize(
    "roles,ok",
    [
        (["operations"], True),
        (["platform_admin", "operations", "platform_admin"], True),  # 去重保序
        (["internal_compliance", "dictionary_admin", "product_reviewer"], True),
        ([], False),
        (["whitelist_owner"], False),  # 客户角色不得进 staff 令牌
        (["platform_admin", "superuser"], False),  # 未知角色
    ],
)
def test_normalize_roles(roles, ok):
    if ok:
        out = service.normalize_roles(roles)
        assert len(out) == len(set(out))
    else:
        with pytest.raises(ValueError):
            service.normalize_roles(roles)


# ---------- 服务层（门控关，自报引导） ----------

async def _issue(session_factory, *, staff_id, staff_name, roles, actor=PA):
    async with session_factory() as session:
        row, secret = await service.issue_staff_key(
            session,
            staff_id=staff_id,
            staff_name=staff_name,
            roles=roles,
            actor=Actor(**actor),
        )
        await session.commit()
        return row, secret


async def test_issue_stores_only_hash_not_plaintext(session_factory):
    row, secret = await _issue(
        session_factory, staff_id="s-1", staff_name="Sam", roles=["operations"]
    )
    async with session_factory() as session:
        got = await session.get(StaffApiKey, row.key_id)
        assert got.status == "active"
        assert got.key_hash == service.hash_key(secret)
        assert secret not in got.key_prefix
        assert got.key_prefix.startswith("loom_staff_")
        assert got.staff_id == "s-1" and got.roles == ["operations"]
        assert got.created_by == "pa-self"


async def test_issue_rbac_denied(session_factory):
    for actor in (OPS, CUSTOMER):
        async with session_factory() as session:
            with pytest.raises(PermissionDenied):
                await service.issue_staff_key(
                    session,
                    staff_id="s",
                    staff_name="n",
                    roles=["operations"],
                    actor=Actor(**actor),
                )


async def test_issue_validation(session_factory):
    async with session_factory() as session:
        invalid = [
            {"staff_id": "  ", "staff_name": "n", "roles": ["operations"]},
            {"staff_id": "s", "staff_name": "", "roles": ["operations"]},
            {"staff_id": "s", "staff_name": "n", "roles": []},
            {"staff_id": "s", "staff_name": "n", "roles": ["whitelist_owner"]},
        ]
        for kwargs in invalid:
            with pytest.raises(ValueError):
                await service.issue_staff_key(session, actor=Actor(**PA), **kwargs)


async def test_verify_wrong_and_revoked(session_factory):
    row, secret = await _issue(
        session_factory, staff_id="s-2", staff_name="Ann", roles=["operations"]
    )
    async with session_factory() as session:
        got = await service.verify_staff_key(session, secret)
        assert got is not None and got.last_used_at is not None
        assert await service.verify_staff_key(session, "loom_staff_nope") is None
        assert await service.verify_staff_key(session, "loom_agentish") is None
        await session.commit()
    async with session_factory() as session:
        revoked = await service.revoke_staff_key(session, row.key_id, Actor(**PA))
        assert revoked.status == "revoked" and revoked.revoked_by == "pa-self"
        await session.commit()
    async with session_factory() as session:
        assert await service.verify_staff_key(session, secret) is None


async def test_revoke_audits_and_rotation(session_factory):
    row_a, _ = await _issue(
        session_factory, staff_id="s-3", staff_name="Bo", roles=["operations"]
    )
    await _issue(session_factory, staff_id="s-3", staff_name="Bo", roles=["operations"])
    async with session_factory() as session:
        # 同一人可持多枚令牌（轮换）。
        rows = (await session.scalars(
            select(StaffApiKey).where(StaffApiKey.staff_id == "s-3")
        )).all()
        assert len(rows) == 2
        await service.revoke_staff_key(session, row_a.key_id, Actor(**PA))
        await session.commit()
        actions = set((await session.scalars(
            select(AuditLog.action).where(AuditLog.entity_id == row_a.key_id)
        )).all())
        assert actions == {"staff_api_key.issue", "staff_api_key.revoke"}


# ---------- HTTP 治理（门控关，V1 自报不破坏） ----------

async def test_http_issue_secret_once_list_masks(client):
    view, secret = await _bootstrap(client, ["platform_admin"])
    assert secret.startswith("loom_staff_") and view["staff_id"] == "s-pa"
    listed = await client.get(
        "/api/admin/staff-keys", params={"actor_id": "pa-self", "roles": "platform_admin"}
    )
    assert listed.status_code == 200
    row = next(r for r in listed.json() if r["key_id"] == view["key_id"])
    assert "secret" not in row and "key_hash" not in row and row["roles"] == ["platform_admin"]


async def test_http_issue_rbac_and_validation(client):
    for actor in (OPS, CUSTOMER):
        resp = await client.post(
            "/api/admin/staff-keys",
            json={"staff_id": "s", "staff_name": "n", "roles": ["operations"], "actor": actor},
        )
        assert resp.status_code == 403
    bad = await client.post(
        "/api/admin/staff-keys",
        json={"staff_id": "s", "staff_name": "n", "roles": ["whitelist_owner"], "actor": PA},
    )
    assert bad.status_code == 422


async def test_http_revoke_flow(client):
    view, _ = await _bootstrap(client, ["operations"], staff_id="s-r", staff_name="Rev")
    denied = await client.post(
        f"/api/admin/staff-keys/{view['key_id']}/revoke", json={"actor": OPS}
    )
    assert denied.status_code == 403
    ok = await client.post(
        f"/api/admin/staff-keys/{view['key_id']}/revoke", json={"actor": PA}
    )
    assert ok.status_code == 200 and ok.json()["status"] == "revoked"
    missing = await client.post(
        "/api/admin/staff-keys/nope/revoke", json={"actor": PA}
    )
    assert missing.status_code == 404


async def test_auth_me_disabled_when_gate_off(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 400


# ---------- 门控开启：核心安全语义 ----------

@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setattr(settings, "staff_auth_enabled", True)
    return settings


async def test_gated_internal_get_requires_token(client, gate_on):
    # 自报 platform_admin 但无令牌 → 401（自报不再被信任）。
    resp = await client.get(
        "/api/admin/tenants", params={"actor_id": "x", "roles": "platform_admin"}
    )
    assert resp.status_code == 401


async def test_gated_internal_get_role_and_escalation(client, monkeypatch):
    # 先在门控关引导签发两枚令牌，再开闸。
    _, ops_secret = await _bootstrap(
        client, ["operations"], staff_id="s-ops", staff_name="Op"
    )
    pa_view, pa_secret = await _bootstrap(
        client, ["platform_admin"], staff_id="s-pa2", staff_name="Pat"
    )
    monkeypatch.setattr(settings, "staff_auth_enabled", True)
    # operations 令牌访问 platform_admin 口 → 403。
    r1 = await client.get(
        "/api/admin/staff-keys",
        params={"actor_id": "s-ops", "roles": "operations"},
        headers=_bearer(ops_secret),
    )
    assert r1.status_code == 403
    # operations 令牌但 query 自报 platform_admin（提权）→ 仍 403。
    r2 = await client.get(
        "/api/admin/tenants",
        params={"actor_id": "s-ops", "roles": "platform_admin"},
        headers=_bearer(ops_secret),
    )
    assert r2.status_code == 403
    # platform_admin 令牌 → 200（即便 query 自报成 operations/他人，以令牌为准）。
    r3 = await client.get(
        "/api/admin/tenants",
        params={"actor_id": "impostor", "roles": "operations"},
        headers=_bearer(pa_secret),
    )
    assert r3.status_code == 200
    r4 = await client.get(
        "/api/admin/staff-keys",
        params={"actor_id": "impostor", "roles": "operations"},
        headers=_bearer(pa_secret),
    )
    assert r4.status_code == 200 and pa_view["key_id"] in {k["key_id"] for k in r4.json()}


async def test_gated_internal_write_requires_token(client, gate_on):
    resp = await client.post(
        "/api/admin/staff-keys",
        json={"staff_id": "s", "staff_name": "n", "roles": ["operations"], "actor": PA},
    )
    assert resp.status_code == 401


async def test_gated_write_escalation_blocked_and_identity_pinned(
    client, monkeypatch, session_factory
):
    # 门控关引导签发，再开闸。
    _, pa_secret = await _bootstrap(
        client, ["platform_admin"], staff_id="real-pa", staff_name="Real PA"
    )
    _, ops_secret = await _bootstrap(
        client, ["operations"], staff_id="real-ops", staff_name="Real Ops"
    )
    monkeypatch.setattr(settings, "staff_auth_enabled", True)
    # operations 令牌 + body 自报 platform_admin 提权签发 → 403。
    esc = await client.post(
        "/api/admin/staff-keys",
        json={
            "staff_id": "x",
            "staff_name": "x",
            "roles": ["platform_admin"],
            "actor": {"id": "impostor", "roles": ["platform_admin"]},
        },
        headers=_bearer(ops_secret),
    )
    assert esc.status_code == 403
    # platform_admin 令牌 + body.actor 自报为他人/低角色 → 201，但 created_by 与审计
    # 都落到令牌真实人员 real-pa（自报被就地覆盖）。
    ok = await client.post(
        "/api/admin/staff-keys",
        json={
            "staff_id": "new-hire",
            "staff_name": "New Hire",
            "roles": ["operations"],
            "actor": {"id": "impostor", "roles": ["operations"]},
        },
        headers=_bearer(pa_secret),
    )
    assert ok.status_code == 201, ok.text
    new_id = ok.json()["key_id"]
    async with session_factory() as session:
        row = await session.get(StaffApiKey, new_id)
        assert row.created_by == "real-pa"  # 不是 body 自报的 impostor
        audit = (await session.scalars(
            select(AuditLog)
            .where(AuditLog.entity_id == new_id, AuditLog.action == "staff_api_key.issue")
            .order_by(AuditLog.created_at.desc())
        )).first()
        assert audit is not None and audit.actor_id == "real-pa"


async def test_gated_tenant_provision_write_globally_gated(
    client, monkeypatch, session_factory
):
    _, pa_secret = await _bootstrap(
        client, ["platform_admin"], staff_id="real-pa", staff_name="Real PA"
    )
    monkeypatch.setattr(settings, "staff_auth_enabled", True)
    # 无令牌 → 401。
    no_token = await client.post(
        "/api/admin/tenants", json={"tenant_id": "t-1", "actor": PA}
    )
    assert no_token.status_code == 401
    # platform_admin 令牌、body actor 自报他人 → 201，审计 actor_id 为令牌人员。
    ok = await client.post(
        "/api/admin/tenants",
        json={"tenant_id": "t-1", "actor": {"id": "impostor", "roles": ["operations"]}},
        headers=_bearer(pa_secret),
    )
    assert ok.status_code == 201, ok.text
    async with session_factory() as session:
        audit = (await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "tenant.provisioned")
            .order_by(AuditLog.created_at.desc())
        )).first()
        assert audit is not None and audit.actor_id == "real-pa"


async def test_gated_invalid_and_revoked_token_401(client, monkeypatch):
    # 门控关引导签发并立即吊销（引导口径），再开闸。
    view, secret = await _bootstrap(
        client, ["platform_admin"], staff_id="s-pa3", staff_name="Pat"
    )
    rev = await client.post(
        f"/api/admin/staff-keys/{view['key_id']}/revoke", json={"actor": PA}
    )
    assert rev.status_code == 200
    monkeypatch.setattr(settings, "staff_auth_enabled", True)
    bad = await client.get(
        "/api/admin/tenants",
        params={"actor_id": "x", "roles": "platform_admin"},
        headers=_bearer("loom_staff_deadbeef"),
    )
    assert bad.status_code == 401
    revoked = await client.get(
        "/api/admin/tenants",
        params={"actor_id": "x", "roles": "platform_admin"},
        headers=_bearer(secret),
    )
    assert revoked.status_code == 401


async def test_gated_agent_keys_list_internal_gate(client, monkeypatch):
    _, pa_secret = await _bootstrap(
        client, ["platform_admin"], staff_id="s-pa4", staff_name="Pat"
    )
    _, ops_secret = await _bootstrap(
        client, ["operations"], staff_id="s-ops2", staff_name="Op"
    )
    monkeypatch.setattr(settings, "staff_auth_enabled", True)
    # 门控开：Q109 原本开放的 agent-keys GET 现在也要 staff platform_admin。
    assert (await client.get("/api/admin/agent-keys")).status_code == 401
    assert (
        await client.get("/api/admin/agent-keys", headers=_bearer(ops_secret))
    ).status_code == 403
    assert (
        await client.get("/api/admin/agent-keys", headers=_bearer(pa_secret))
    ).status_code == 200


async def test_gated_auth_me(client, monkeypatch):
    _, pa_secret = await _bootstrap(
        client, ["platform_admin", "operations"], staff_id="s-me", staff_name="Me"
    )
    monkeypatch.setattr(settings, "staff_auth_enabled", True)
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (
        await client.get("/api/auth/me", headers=_bearer("loom_staff_bad"))
    ).status_code == 401
    ok = await client.get("/api/auth/me", headers=_bearer(pa_secret))
    assert ok.status_code == 200
    assert ok.json() == {
        "staff_id": "s-me",
        "staff_name": "Me",
        "roles": ["platform_admin", "operations"],
    }


async def test_gated_public_customer_and_agent_prefix_unaffected(client, gate_on):
    # 公开健康检查：无令牌 200。
    assert (await client.get("/healthz")).status_code == 200
    # 机器 Agent 前缀（loom_，非 staff）不被 staff 认证当坏令牌误杀。
    assert (
        await client.get("/healthz", headers=_bearer("loom_someagentkey"))
    ).status_code == 200
    # 客户只读口（无内部角色闸）：门控开无 staff 令牌不被拦（未知租户 404，而非 401）。
    resp = await client.get("/api/tenants/unknown-tenant")
    assert resp.status_code == 404
    # 机器回调口（/api/effect-callback）与 A2A 走 loom_ Agent Key 独立鉴权：其 staff
    # 前缀分流已由上面的 healthz + loom_ 前缀 200 证明（不会被 staff 认证误杀），
    # Agent Key 401 行为由 test_agent_api_keys / effect-callback 既有测试覆盖。
