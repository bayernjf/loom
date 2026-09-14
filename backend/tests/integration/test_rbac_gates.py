"""RBAC 红线收口（M10 切片 d，Q75）：新收口端点的 403 矩阵。

有意开放的 pws/evaluate 与 atom revive 不在此列（Q75 第 4 条）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app

OPS = {"id": "ops-1", "roles": ["operations"]}
DICT_ADMIN = {"id": "dict-1", "roles": ["dictionary_admin"]}
COMPLIANCE = {"id": "ic-1", "roles": ["internal_compliance"]}
PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
NOBODY = {"id": "nobody-1", "roles": []}


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


# ---- C1 配置写：operations（Q2/Q7，既有裁决本次补闸） ----

async def test_signal_weights_require_operations(client):
    body = {
        "rows": [
            {"signal": "name", "signal_name": "产品名", "enabled": True, "weight": 1.0}
        ],
        "actor": NOBODY,
    }
    assert (await client.put("/api/admin/c1/signal-weights", json=body)).status_code == 403
    body["actor"] = PLATFORM_ADMIN
    assert (await client.put("/api/admin/c1/signal-weights", json=body)).status_code == 403
    body["actor"] = OPS
    assert (await client.put("/api/admin/c1/signal-weights", json=body)).status_code == 200


async def test_industry_crud_requires_operations(client):
    item = {"industry": "beauty", "threshold": 0.8}
    assert (
        await client.post(
            "/api/admin/c1/industries", json={"item": item, "actor": NOBODY}
        )
    ).status_code == 403
    assert (
        await client.patch(
            "/api/admin/c1/industries/beauty", json={"threshold": 0.9, "actor": NOBODY}
        )
    ).status_code == 403
    assert (
        await client.request(
            "DELETE", "/api/admin/c1/industries/beauty", json={"actor": NOBODY}
        )
    ).status_code == 403
    # 角色闸先于存在性检查：operations 打不存在的行业得 404 而非 403。
    assert (
        await client.request(
            "DELETE", "/api/admin/c1/industries/beauty", json={"actor": OPS}
        )
    ).status_code == 404


# ---- G1 全局字典写：dictionary_admin（Q75 第 2 条） ----

async def test_category_and_template_require_dictionary_admin(client):
    assert (
        await client.post("/api/categories", json={"name": "护肤", "actor": NOBODY})
    ).status_code == 403
    assert (
        await client.post(
            "/api/categories", json={"name": "护肤", "actor": PLATFORM_ADMIN}
        )
    ).status_code == 403
    resp = await client.post(
        "/api/categories", json={"name": "护肤", "actor": DICT_ADMIN}
    )
    assert resp.status_code == 201
    category_id = resp.json()["category_id"]

    tpl_body = {"field_list": [], "status": "draft", "actor": NOBODY}
    assert (
        await client.put(
            f"/api/categories/{category_id}/template", json=tpl_body
        )
    ).status_code == 403
    tpl_body["actor"] = OPS
    assert (
        await client.put(
            f"/api/categories/{category_id}/template", json=tpl_body
        )
    ).status_code == 403
    tpl_body["actor"] = DICT_ADMIN
    assert (
        await client.put(
            f"/api/categories/{category_id}/template", json=tpl_body
        )
    ).status_code == 200


# ---- 字段来源路由：operations（Q8，既有裁决本次补闸） ----

async def test_source_routes_require_operations(client):
    item = {"route": "r1", "name": "用户输入"}
    assert (
        await client.put(
            "/api/admin/fp-source-routes/r1", json={"item": item, "actor": NOBODY}
        )
    ).status_code == 403
    assert (
        await client.put(
            "/api/admin/fp-source-routes/r1", json={"item": item, "actor": OPS}
        )
    ).status_code == 200
    assert (
        await client.request(
            "DELETE", "/api/admin/fp-source-routes/r1", json={"actor": NOBODY}
        )
    ).status_code == 403
    assert (
        await client.request(
            "DELETE", "/api/admin/fp-source-routes/r1", json={"actor": OPS}
        )
    ).status_code == 200


# ---- 手工 sweep：platform_admin（Q75 第 1 条） ----

async def test_sweeps_require_platform_admin(client):
    assert (
        await client.post(
            "/api/admin/ops-todos/sweep", json={"actor": NOBODY}
        )
    ).status_code == 403
    assert (
        await client.post("/api/admin/ops-todos/sweep", json={"actor": OPS})
    ).status_code == 403
    assert (
        await client.post(
            "/api/admin/ops-todos/sweep", json={"actor": PLATFORM_ADMIN}
        )
    ).status_code == 200

    assert (
        await client.post("/api/admin/sla/run", json={"actor": COMPLIANCE})
    ).status_code == 403
    # 缺 actor body = 422（契约要求），不是放行。
    assert (await client.post("/api/admin/sla/run")).status_code == 422
    ok = await client.post("/api/admin/sla/run", json={"actor": PLATFORM_ADMIN})
    assert ok.status_code == 200


# ---- CCR 机械清洗触发：internal_compliance（Q75 第 3 条） ----

async def test_ccr_run_requires_internal_compliance(client):
    # 角色闸先于 PWS 存在性：错角色 403；对角色给不存在 PWS 才是 404。
    assert (
        await client.post("/api/pws/nope/ccr/run", json={"actor": OPS})
    ).status_code == 403
    assert (
        await client.post("/api/pws/nope/ccr/run", json={"actor": COMPLIANCE})
    ).status_code == 404
