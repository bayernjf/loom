"""变更-回滚清单读口集成测试（Q334，design-v3-rollback-center §3.1 甲）。

内存 SQLite + httpx ASGI 直插 audit_logs，测五机制聚合口径、rollbackability
标注、mechanism 过滤、RBAC；只读面不产生任何写入。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.main import app


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


async def _seed(factory) -> None:
    rows = [
        ("config.update", "config_item", "platform.recalc_step", "pa-1"),
        ("pws.freeze", "pws_snapshot", "snap-1", "op-1"),
        ("fcw.issued", "fcw", "final-1", "op-1"),
        ("wl.update", "compliance_wordlist", "wl-1", "ic-1"),
        ("skill_prompt.publish", "skill_prompt", "PT-CONTENT-GOAL-PLAN", "pa-1"),
        # 非五机制的写动作不得混入聚合面
        ("tenant.plan_changed", "tenant", "t-1", "pa-1"),
    ]
    async with factory() as s:
        for action, etype, eid, actor in rows:
            s.add(
                AuditLog(
                    tenant_id="t-1",
                    actor_id=actor,
                    actor_roles=["operations"],
                    action=action,
                    entity_type=etype,
                    entity_id=eid,
                    detail={"k": "v"},
                )
            )
        await s.commit()


def _q(actor="pa-1", roles="platform_admin", **extra):
    qs = f"actor_id={actor}&roles={roles}"
    for k, v in extra.items():
        qs += f"&{k}={v}"
    return qs


async def test_aggregates_five_mechanisms_and_marks_rollbackability(client, session_factory):
    await _seed(session_factory)
    resp = await client.get("/api/admin/change-ledger?" + _q())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5  # tenant.plan_changed 被排除
    by_action = {item["action"]: item for item in data["items"]}
    assert by_action["config.update"]["rollbackability"] == "rollbackable"
    assert by_action["pws.freeze"]["rollbackability"] == "revoke_reissue"
    assert by_action["fcw.issued"]["rollbackability"] == "revoke_reissue"
    assert by_action["wl.update"]["rollbackability"] == "reedit_only"
    assert by_action["skill_prompt.publish"]["rollbackability"] == "no_surface"
    assert by_action["config.update"]["mechanism"] == "config_center"
    assert by_action["skill_prompt.publish"]["mechanism"] == "skill_prompt"
    assert "/rollback" in by_action["config.update"]["ops_surface"]


async def test_mechanism_filter(client, session_factory):
    await _seed(session_factory)
    resp = await client.get(
        "/api/admin/change-ledger?" + _q(mechanism="fcw")
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["action"] == "fcw.issued"


async def test_unknown_mechanism_returns_empty(client, session_factory):
    await _seed(session_factory)
    resp = await client.get(
        "/api/admin/change-ledger?" + _q(mechanism="nope")
    )
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "items": []}


async def test_rbac_operations_allowed_nobody_403(client, session_factory):
    await _seed(session_factory)
    ok = await client.get("/api/admin/change-ledger?" + _q(actor="op-1", roles="operations"))
    assert ok.status_code == 200
    bad = await client.get("/api/admin/change-ledger?" + _q(actor="x", roles="customer"))
    assert bad.status_code == 403
    missing = await client.get("/api/admin/change-ledger")
    assert missing.status_code == 422
