"""Q196 口径 B 甲／A 甲：审计身份与租户归属的收口证据。

B 甲＝"凭证优先于自报"落在唯一写口 ``append_audit``（引擎级，调用点无从绕过）；
A 甲＝审计记录的租户以被操作对象行上的归属为准，不再抄调用方声明。

这里刻意用**真实端点**跑，而不是直接调函数：要证的正是"带凭证打客户写口时，
自报身份进不了审计"这条穿过认证依赖、RBAC、服务层与落库的链路。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.content.models import CONTENT_READY, ContentProduct
from app.core.actor import Actor
from app.core.api_keys import service as agent_service
from app.core.audit import append_audit, audit_identity
from app.core.db import Base, get_session, settings
from app.core.effects import service as effects_service
from app.core.effects.schemas import CustomerEffectBatchIn, EffectRecordIn
from app.core.identity import (
    CREDENTIAL_AGENT_KEY,
    CREDENTIAL_NONE,
    CREDENTIAL_STAFF,
    reset_verified_credential,
    set_verified_credential,
)
from app.core.models import AuditLog
from app.core.staff_auth import service as staff_service
from app.core.staff_auth.deps import get_auth_session
from app.main import app

PA = {"id": "pa-self", "roles": ["platform_admin"]}
IMPOSTOR = {"id": "pretended-victim", "roles": ["platform_admin"]}


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
    async with factory() as session:
        session.add(
            ContentProduct(
                content_id="c1",
                tenant_id="t1",
                product_space_id="ps-1",
                final_id="fcw-1",
                goal="种草",
                platform="douyin",
                status=CONTENT_READY,
            )
        )
        await session.commit()
    yield factory
    app.dependency_overrides.clear()
    reset_verified_credential()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _backfill_body(actor: dict) -> dict:
    return {
        "tenant_id": "t1",
        "actor": actor,
        "records": [
            {
                "content_id": "c1",
                "platform_post_id": "p1",
                "captured_at": "2026-09-01T10:00:00Z",
                "metrics": {"plays": 10},
            }
        ],
    }


async def _audit_rows(session_factory, action: str) -> list[AuditLog]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == action)
                )
            ).all()
        )


async def _issue_staff_key(session_factory, *, staff_id: str, roles: list[str]):
    async with session_factory() as session:
        _row, secret = await staff_service.issue_staff_key(
            session,
            staff_id=staff_id,
            staff_name=staff_id,
            roles=roles,
            actor=Actor(id=PA["id"], roles=PA["roles"]),
        )
        await session.commit()
    return secret


@pytest.fixture(autouse=True)
def _clean_credential_context():
    """每个用例前后都清一次"已验真凭证"，防用例间相互污染。"""
    reset_verified_credential()
    yield
    reset_verified_credential()


# ---------- 纯函数：凭证 > 自报的三种落点 ----------


def test_no_credential_keeps_declared_identity_and_labels_it():
    actor_id, roles, via, extra = audit_identity("cust-1", ["customer"])
    assert (actor_id, roles, via) == ("cust-1", ["customer"], CREDENTIAL_NONE)
    assert extra == {}


def test_verified_credential_replaces_declared_and_keeps_it_as_evidence():
    set_verified_credential(Actor(id="s-ops", roles=["operations"]), CREDENTIAL_STAFF)
    actor_id, roles, via, extra = audit_identity("pretended-victim", ["platform_admin"])
    assert (actor_id, roles, via) == ("s-ops", ["operations"], CREDENTIAL_STAFF)
    assert extra["declared_actor"] == {
        "id": "pretended-victim",
        "roles": ["platform_admin"],
    }


def test_matching_declared_identity_adds_no_noise():
    set_verified_credential(Actor(id="s-ops", roles=["operations"]), CREDENTIAL_STAFF)
    _, _, via, extra = audit_identity("s-ops", ["operations"])
    assert via == CREDENTIAL_STAFF
    assert extra == {}


def test_agent_key_credential_is_a_credential_too():
    set_verified_credential(Actor(id="key-9", roles=[]), CREDENTIAL_AGENT_KEY)
    actor_id, roles, via, _ = audit_identity("whoever", ["platform_admin"])
    assert (actor_id, roles, via) == ("key-9", [], CREDENTIAL_AGENT_KEY)


# ---------- 端点：客户写口带上 staff 令牌时，自报身份进不了审计 ----------


async def test_customer_write_with_staff_token_audits_the_person_not_the_claim(
    client, session_factory, monkeypatch
):
    secret = await _issue_staff_key(session_factory, staff_id="s-real", roles=["operations"])
    monkeypatch.setattr(settings, "staff_auth_enabled", True)

    r = await client.post(
        "/api/effects/backfill",
        json=_backfill_body(IMPOSTOR),
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert r.status_code == 200, r.text

    rows = await _audit_rows(session_factory, "effect.customer_backfilled")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_id == "s-real"
    assert row.actor_roles == ["operations"]
    assert row.detail["_actor_via"] == CREDENTIAL_STAFF
    # 自报值不丢，降级为备查证据。
    assert row.detail["declared_actor"]["id"] == "pretended-victim"
    # 口径 A 甲：审计租户来自命中成品行，而非调用方声明。
    assert row.tenant_id == "t1"


async def test_caller_supplied_provenance_cannot_override_the_server_label(
    session_factory,
):
    """``detail`` 里塞 ``_actor_via`` 不顶事——来源标签由服务端最后写。

    这是留痕字段自身的提权面：若调用方能决定 ``_actor_via``，一条伪造的
    ``staff_token`` 就能让未证实的自报身份看起来像持凭证者所为。
    """

    async with session_factory() as session:
        await append_audit(
            session,
            tenant_id="t1",
            actor_id="whoever",
            actor_roles=["platform_admin"],
            action="test.forged_provenance",
            entity_type="probe",
            entity_id="p-1",
            detail={"_actor_via": CREDENTIAL_STAFF, "declared_actor": "looks-verified"},
        )
        await session.commit()

    rows = await _audit_rows(session_factory, "test.forged_provenance")
    assert rows[0].detail["_actor_via"] == CREDENTIAL_NONE
    assert rows[0].actor_id == "whoever"


async def test_customer_write_without_credential_is_labelled_declared(
    client, session_factory
):
    r = await client.post("/api/effects/backfill", json=_backfill_body(PA))
    assert r.status_code == 200, r.text

    rows = await _audit_rows(session_factory, "effect.customer_backfilled")
    assert len(rows) == 1
    assert rows[0].actor_id == "pa-self"
    assert rows[0].detail["_actor_via"] == CREDENTIAL_NONE
    assert "declared_actor" not in rows[0].detail


async def test_agent_channel_audits_the_key_that_was_verified(
    client, session_factory
):
    async with session_factory() as session:
        row, secret = await agent_service.issue_key(
            session, "eff", Actor(id=PA["id"], roles=PA["roles"])
        )
        await session.commit()
    key_id = row.key_id

    r = await client.post(
        "/api/effect-callback",
        json={
            "source": "agent",
            "records": [
                {
                    "content_id": "c1",
                    "platform_post_id": "p2",
                    "captured_at": "2026-09-02T10:00:00Z",
                    "metrics": {"plays": 1},
                }
            ],
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert r.status_code == 200, r.text

    rows = await _audit_rows(session_factory, "effect.batch_received")
    assert rows[0].actor_id == key_id
    assert rows[0].detail["_actor_via"] == CREDENTIAL_AGENT_KEY


async def test_credential_does_not_leak_into_the_next_unauthenticated_request(
    client, session_factory
):
    """打过一次带凭证的口，紧接着的无凭证请求不得沿用那个身份。

    生产里每个请求本就是独立 task、contextvar 天然隔离；这条守的是"每请求先清零"
    这个前提本身——一旦哪天换了复用上下文的执行路径（或像这里一样在同一上下文里
    连打两次），审计不会把上一条请求的凭证身份算到这一条头上。
    """

    async with session_factory() as session:
        _row, secret = await agent_service.issue_key(
            session, "eff2", Actor(id=PA["id"], roles=PA["roles"])
        )
        await session.commit()

    first = await client.post(
        "/api/effect-callback",
        json={
            "source": "agent",
            "records": [
                {
                    "content_id": "c1",
                    "platform_post_id": "p7",
                    "captured_at": "2026-09-05T10:00:00Z",
                }
            ],
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert first.status_code == 200, first.text

    second = await client.post("/api/effects/backfill", json=_backfill_body(PA))
    assert second.status_code == 200, second.text

    rows = await _audit_rows(session_factory, "effect.customer_backfilled")
    assert [r.actor_id for r in rows] == ["pa-self"]
    assert rows[-1].detail["_actor_via"] == CREDENTIAL_NONE


# ---------- 口径 A 甲：审计租户以对象为准，声明只作交叉校验 ----------


async def test_audit_tenant_is_taken_from_the_content_row_not_the_caller(
    session_factory,
):
    """声明一个从未命中过的租户不可能通过校验：整批 422，且不留审计。"""

    async with session_factory() as session:
        batch = CustomerEffectBatchIn(
            tenant_id="intruder",
            actor=Actor(id="x", roles=[]),
            records=[
                EffectRecordIn(
                    content_id="c1",
                    platform_post_id="p3",
                    captured_at="2026-09-03T10:00:00+00:00",
                )
            ],
        )
        with pytest.raises(effects_service.EffectValidationError):
            await effects_service.ingest_customer_backfill(session, batch=batch)
        await session.rollback()
    rows = await _audit_rows(session_factory, "effect.customer_backfilled")
    assert rows == []


async def test_audit_tenant_follows_the_object_even_if_the_filter_ever_widens(
    session_factory, monkeypatch
):
    """A 甲的可证伪版：把解析结果换成"另一租户的成品"，审计租户必须跟着**对象**走。

    今天这条路径按声明租户过滤、派生值恒等于声明值，所以正常用例证不到差异；
    这里刻意伪造一个放宽过滤后的世界（例如日后接入 Q127 认领兜底），钉住"权威是
    成品行上的 tenant_id，不是调用方声明的字符串"。
    """

    async with session_factory() as session:
        session.add(
            ContentProduct(
                content_id="c9",
                tenant_id="elsewhere",
                product_space_id="ps-9",
                final_id="fcw-9",
                goal="种草",
                platform="douyin",
                status=CONTENT_READY,
            )
        )
        await session.commit()

    original_resolve = effects_service._resolve_contents

    async def _wide(_session, external_ids, *, tenant_id=None):
        # 忽略调用方声明的 tenant_id，返回别的租户的成品。
        return await original_resolve(_session, external_ids)

    monkeypatch.setattr(effects_service, "_resolve_contents", _wide)

    async with session_factory() as session:
        receipt = await effects_service.ingest_customer_backfill(
            session,
            batch=CustomerEffectBatchIn(
                tenant_id="caller-claimed",
                actor=Actor(id="x", roles=[]),
                records=[
                    EffectRecordIn(
                        content_id="c9",
                        platform_post_id="p9",
                        captured_at="2026-09-04T10:00:00+00:00",
                    )
                ],
            ),
        )
        await session.commit()
    assert receipt["matched"] == 1

    rows = await _audit_rows(session_factory, "effect.customer_backfilled")
    assert [r.tenant_id for r in rows] == ["elsewhere"]
    assert "caller-claimed" not in {r.tenant_id for r in rows}
