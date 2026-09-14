"""配置中心 API 集成测试（08 M10 验收行：40+ 项后台可配、版本化、回滚、writeAudit、热更新缓存）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config_center.cache import config_cache
from app.core.config_center.models import ConfigItem, ConfigItemVersion
from app.core.config_center.seeds import CONFIG_SEEDS
from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.main import app

ADMIN = {"id": "admin-1", "roles": ["platform_admin"]}
NOBODY = {"id": "nobody-1", "roles": ["operations"]}

KEY = "pwc.funnel_batch_limit"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        for key, category, value_type, value, source_ref, validation in CONFIG_SEEDS:
            session.add(
                ConfigItem(
                    key=key,
                    category=category,
                    value=value,
                    value_type=value_type,
                    validation=validation,
                    source_ref=source_ref,
                    version=1,
                )
            )
            session.add(
                ConfigItemVersion(
                    version_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-config-seed:{key}")),
                    key=key,
                    version=1,
                    value=value,
                    change_note="C2 seed",
                )
            )
        await session.commit()

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    config_cache.invalidate()
    yield factory
    app.dependency_overrides.clear()
    config_cache.invalidate()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_list_and_filter_seeded_items(client):
    resp = await client.get("/api/admin/config")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == len(CONFIG_SEEDS)
    assert {r["key"] for r in rows} >= {
        "c1.cold_start_floor",
        "fcw.w_pwc_skeleton",
        "agent.support_max_tokens",
    }
    pwc = await client.get("/api/admin/config", params={"category": "pwc"})
    assert all(r["category"] == "pwc" for r in pwc.json())
    one = await client.get(f"/api/admin/config/{KEY}")
    assert one.json()["value"] == 50 and one.json()["version"] == 1
    assert (await client.get("/api/admin/config/nope.key")).status_code == 404


async def test_update_publishes_version_audit_and_hot_reload(client, session_factory):
    resp = await client.put(
        f"/api/admin/config/{KEY}",
        json={"value": 60, "change_note": "高峰期放宽", "actor": ADMIN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["value"] == 60 and body["version"] == 2 and body["updated_by"] == "admin-1"

    history = (await client.get(f"/api/admin/config/{KEY}/history")).json()
    assert [r["version"] for r in history] == [2, 1]
    assert history[1]["change_note"] == "C2 seed"

    # 提交后进程内快照已热切换（14 §2.4 原子切换）
    assert config_cache.get_int(KEY, 0) == 60

    async with session_factory() as session:
        logs = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_type == "config_item", AuditLog.entity_id == KEY
                )
            )
        ).all()
        assert [log.action for log in logs] == ["config.update"]
        assert logs[0].detail["version"] == 2


async def test_rollback_restores_historical_value_as_new_version(client):
    await client.put(
        f"/api/admin/config/{KEY}", json={"value": 60, "actor": ADMIN}
    )
    back = await client.post(
        f"/api/admin/config/{KEY}/rollback",
        json={"target_version": 1, "actor": ADMIN},
    )
    assert back.status_code == 200, back.text
    body = back.json()
    assert body["value"] == 50 and body["version"] == 3
    history = (await client.get(f"/api/admin/config/{KEY}/history")).json()
    assert [r["version"] for r in history] == [3, 2, 1]
    assert history[0]["change_note"] == "rollback to v1"


async def test_validation_role_and_404_guards(client):
    # 越权
    denied = await client.put(
        f"/api/admin/config/{KEY}", json={"value": 60, "actor": NOBODY}
    )
    assert denied.status_code == 403
    # 越界 422（min=1）
    bad = await client.put(
        f"/api/admin/config/{KEY}", json={"value": 0, "actor": ADMIN}
    )
    assert bad.status_code == 422
    # 类型不符 422
    wrong_type = await client.put(
        f"/api/admin/config/{KEY}", json={"value": 1.5, "actor": ADMIN}
    )
    assert wrong_type.status_code == 422
    # 未知键
    missing = await client.put(
        "/api/admin/config/nope.key", json={"value": 1, "actor": ADMIN}
    )
    assert missing.status_code == 404
    # 回滚到不存在的版本
    no_version = await client.post(
        f"/api/admin/config/{KEY}/rollback",
        json={"target_version": 99, "actor": ADMIN},
    )
    assert no_version.status_code == 404
    # 值未被任何失败请求改动
    assert (await client.get(f"/api/admin/config/{KEY}")).json()["version"] == 1


async def test_failed_update_does_not_touch_cache(client):
    config_cache.apply({KEY: 50})
    bad = await client.put(
        f"/api/admin/config/{KEY}", json={"value": -1, "actor": ADMIN}
    )
    assert bad.status_code == 422
    assert config_cache.get_int(KEY, 0) == 50
