"""P0 集成测试：客户访问令牌（client_access_tokens）与客户决策端点强制认证。

覆盖四层：
1. 纯函数：明文仅一次、只存 SHA-256、前缀分域（loom_client_ 与 loom_staff_/loom_）；
2. 服务层：签发存哈希不存明文、运营 RBAC、验签（错误/吊销/租户不符统一 None）、吊销；
3. HTTP 治理：签发/列表不泄密、RBAC、吊销；
4. 端点安全：客户决策写口无令牌 401、错误/他租户/其他前缀令牌 401、正确令牌 200，
   且请求体自报 actor 不再决定身份。

create_all 不跑迁移；内存 SQLite。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_READY, CONTENT_REVIEW, ContentProduct
from app.core.actor import Actor
from app.core.client_auth import service
from app.core.client_auth.models import ClientAccessToken
from app.core.db import Base, get_session
from app.core.rbac import WHITELIST_OWNER, PermissionDenied
from app.main import app

PA = {"id": "pa-self", "roles": ["platform_admin"]}
OPS = {"id": "ops-self", "roles": ["operations"]}
CUSTOMER = {"id": "cust-1", "roles": []}
RANDOM_CUSTOMER = {"id": "rand", "roles": ["customer"]}


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
        # 两个租户各一篇 review 态成品，可用于 approve 与跨租户负向用例。
        session.add_all([
            ContentProduct(
                content_id="cp-t1", tenant_id="t1", product_space_id="ps-1",
                final_id="fcw-1", goal="种草", platform="douyin",
                status=CONTENT_REVIEW,
            ),
            ContentProduct(
                content_id="cp-t2", tenant_id="t2", product_space_id="ps-2",
                final_id="fcw-2", goal="种草", platform="douyin",
                status=CONTENT_REVIEW,
            ),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- 纯函数 ----------

def test_generate_client_key_shape_and_uniqueness():
    seen = set()
    for _ in range(20):
        plaintext, digest, prefix = service.generate_client_key()
        seen.add(plaintext)
        assert plaintext.startswith("loom_client_")
        assert digest == service.hash_key(plaintext)
        assert len(digest) == 64
        assert plaintext.startswith(prefix)
    assert len(seen) == 20


def test_prefix_domains_are_distinct():
    assert service.is_client_token("loom_client_abc") is True
    # 内部 staff 与机器 agent 前缀都不是客户令牌。
    assert service.is_client_token("loom_staff_abc") is False
    assert service.is_client_token("loom_abc") is False
    assert service.is_client_token(None) is False
    assert service.is_client_token("") is False


# ---------- 服务层 ----------

async def _issue(session_factory, *, tenant_id="t1", client_name="cust-1", actor=OPS):
    async with session_factory() as session:
        row, secret = await service.issue_client_key(
            session, tenant_id=tenant_id, client_name=client_name,
            actor=Actor(**actor),
        )
        await session.commit()
        return row, secret


async def test_issue_stores_only_hash_not_plaintext(session_factory):
    row, secret = await _issue(session_factory, client_name="张三")
    async with session_factory() as session:
        got = await session.get(ClientAccessToken, row.token_id)
        assert got.status == "active"
        assert got.key_hash == service.hash_key(secret)
        assert secret not in got.key_prefix
        assert got.key_prefix.startswith("loom_client_")
        assert got.tenant_id == "t1" and got.client_name == "张三"
        assert got.created_by == "ops-self"


async def test_issue_rbac_denied(session_factory):
    # 非 platform_admin/operations 不能签发客户令牌。
    for actor in (CUSTOMER, RANDOM_CUSTOMER):
        async with session_factory() as session:
            with pytest.raises(PermissionDenied):
                await service.issue_client_key(
                    session, tenant_id="t1", client_name="x",
                    actor=Actor(**actor),
                )


async def test_issue_validation(session_factory):
    async with session_factory() as session:
        for kwargs in (
            {"tenant_id": "  ", "client_name": "x"},
            {"tenant_id": "t1", "client_name": ""},
        ):
            with pytest.raises(ValueError):
                await service.issue_client_key(
                    session, actor=Actor(**PA), **kwargs
                )


async def test_verify_wrong_revoked_and_tenant_mismatch(session_factory):
    row, secret = await _issue(session_factory, tenant_id="t1")
    async with session_factory() as session:
        # 正确令牌、正确租户命中。
        got = await service.verify_client_key(session, secret, "t1")
        assert got is not None and got.last_used_at is not None
        # 错误令牌 / 错误前缀统一 None。
        assert await service.verify_client_key(session, "loom_client_nope", "t1") is None
        assert await service.verify_client_key(session, "loom_staff_abc", "t1") is None
        # 同令牌但声明他租户 → None（租户归属强制）。
        assert await service.verify_client_key(session, secret, "t2") is None
        await session.commit()

    async with session_factory() as session:
        revoked = await service.revoke_client_key(session, row.token_id, Actor(**PA))
        assert revoked.status == "revoked"
        await session.commit()

    async with session_factory() as session:
        assert await service.verify_client_key(session, secret, "t1") is None


async def test_client_actor_identity(session_factory):
    row, _ = await _issue(session_factory, client_name="李四")
    actor = service.client_actor(row)
    assert actor.id == "李四"
    assert actor.roles == [WHITELIST_OWNER]


# ---------- HTTP 治理 ----------

async def _bootstrap(client, *, tenant_id="t1", client_name="cust-1", actor=OPS):
    resp = await client.post(
        "/api/admin/client-keys",
        json={
            "tenant_id": tenant_id, "client_name": client_name, "actor": actor,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json(), resp.json()["secret"]


async def test_http_issue_and_list_masks_secret(client):
    view, secret = await _bootstrap(client, client_name="王五")
    assert secret.startswith("loom_client_")
    assert view["client_name"] == "王五"
    listed = await client.get(
        "/api/admin/client-keys",
        params={"actor_id": "ops-self", "roles": "operations"},
    )
    assert listed.status_code == 200, listed.text
    row = next(r for r in listed.json() if r["token_id"] == view["token_id"])
    assert "secret" not in row and "key_hash" not in row
    assert row["tenant_id"] == "t1" and row["status"] == "active"


async def test_http_issue_rbac_denied(client):
    for actor in (CUSTOMER, RANDOM_CUSTOMER):
        resp = await client.post(
            "/api/admin/client-keys",
            json={"tenant_id": "t1", "client_name": "x", "actor": actor},
        )
        assert resp.status_code == 403


async def test_http_revoke_flow(client):
    view, _ = await _bootstrap(client)
    # 非运营不能吊销。
    denied = await client.post(
        f"/api/admin/client-keys/{view['token_id']}/revoke",
        json={"actor": CUSTOMER},
    )
    assert denied.status_code == 403
    ok = await client.post(
        f"/api/admin/client-keys/{view['token_id']}/revoke",
        json={"actor": PA},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "revoked"
    missing = await client.post(
        "/api/admin/client-keys/nope/revoke", json={"actor": PA}
    )
    assert missing.status_code == 404


# ---------- 端点强制认证（核心安全语义） ----------

async def test_decision_endpoint_without_token_is_401(client):
    # 无 Authorization，即便 body 自报 actor 也 401（自报不是身份）。
    r = await client.post(
        "/api/content/cp-t1/approve?tenant_id=t1", json={"actor": CUSTOMER}
    )
    assert r.status_code == 401, r.text


async def test_decision_endpoint_bad_and_cross_prefix_token_401(client):
    # 伪造/错误客户令牌。
    r = await client.post(
        "/api/content/cp-t1/approve?tenant_id=t1",
        json={"actor": CUSTOMER},
        headers={"Authorization": "Bearer loom_client_deadbeef"},
    )
    assert r.status_code == 401
    # 内部 staff 或机器 agent 前缀不能当客户令牌。
    for prefix in ("loom_staff_x", "loom_agent_x"):
        r = await client.post(
            "/api/content/cp-t1/approve?tenant_id=t1",
            json={"actor": CUSTOMER},
            headers={"Authorization": f"Bearer {prefix}"},
        )
        assert r.status_code == 401, f"{prefix}: {r.text}"


async def test_decision_endpoint_tenant_mismatch_token_401(client):
    # 为 t1 签发的令牌，却声明 t2 打 t2 资源 → 401（租户归属强制）。
    _, secret_t1 = await _bootstrap(client, tenant_id="t1")
    r = await client.post(
        "/api/content/cp-t2/approve?tenant_id=t2",
        json={"actor": CUSTOMER},
        headers={"Authorization": f"Bearer {secret_t1}"},
    )
    assert r.status_code == 401, r.text


async def test_decision_endpoint_valid_token_200_and_identity_pinned(client):
    _view, secret = await _bootstrap(client, client_name="cust-1")
    # body 里故意自报成另一个高角色身份；认证后以令牌身份为准，approve 成功。
    r = await client.post(
        "/api/content/cp-t1/approve?tenant_id=t1",
        json={"actor": {"id": "impostor", "roles": ["platform_admin"]}},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_READY


async def test_body_edit_endpoint_requires_token(client):
    # PATCH body 同样强制客户令牌：无令牌 401，而非进入业务校验。
    r = await client.patch(
        "/api/content/cp-t1/body?tenant_id=t1",
        json={"body": "x", "actor": CUSTOMER},
    )
    assert r.status_code == 401, r.text
