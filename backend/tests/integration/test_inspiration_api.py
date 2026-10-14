"""段3 灵感库本体集成测试（Q358）：CRUD + RBAC + 层校验 + DIM-SOURCE 上下文查询。

沿用 test_skill7_wf02_api.py 的 sqlite 内存 fixture（Base.metadata.create_all）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.tenants.models import Tenant
from app.main import app
from app.product.inspiration import service as inspiration_service
from app.product.inspiration.models import InspirationEntry
from app.product.product_intake.models import ProductSpace

OPS = {"id": "ops-1", "roles": ["operations"]}
ADMIN = {"id": "admin-1", "roles": ["platform_admin"]}
NOBODY = {"id": "nobody-1", "roles": []}


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
        session.add(Tenant(tenant_id="t1"))
        session.add(
            ProductSpace(
                product_space_id="ps1",
                tenant_id="t1",
                intake_id="intake-1",
                profile_snapshot={},
            )
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _create_common(actor=OPS, content="通用灵感 A"):
    return {
        "tenant_id": "t1",
        "layer": "common",
        "product_space_id": None,
        "content": content,
        "tags": ["tag1"],
        "enabled": True,
        "actor": actor,
    }


def _create_product(actor=OPS, content="产品灵感 B"):
    return {
        "tenant_id": "t1",
        "layer": "product",
        "product_space_id": "ps1",
        "content": content,
        "tags": [],
        "enabled": True,
        "actor": actor,
    }


def _view(actor: dict) -> dict:
    return {"actor_id": actor["id"], "roles": actor["roles"]}


# ---- 创建 ----

async def test_create_common_requires_writer(client):
    r = await client.post("/api/admin/inspiration-entries", json=_create_common(NOBODY))
    assert r.status_code == 403


async def test_create_common_and_product(client):
    r1 = await client.post("/api/admin/inspiration-entries", json=_create_common())
    assert r1.status_code == 201
    assert r1.json()["layer"] == "common"
    assert r1.json()["product_space_id"] is None
    assert r1.json()["usage_count"] == 0

    r2 = await client.post("/api/admin/inspiration-entries", json=_create_product())
    assert r2.status_code == 201
    assert r2.json()["layer"] == "product"
    assert r2.json()["product_space_id"] == "ps1"


async def test_product_layer_requires_product_space_id(client):
    body = _create_common()
    body["layer"] = "product"
    # 仍带 product_space_id=None → 校验失败
    r = await client.post("/api/admin/inspiration-entries", json=body)
    assert r.status_code == 422


async def test_common_layer_must_not_set_product_space_id(client):
    body = _create_product()
    body["layer"] = "common"
    # product 层改成 common 但保留 product_space_id → 校验失败
    r = await client.post("/api/admin/inspiration-entries", json=body)
    assert r.status_code == 422


# ---- 列表 + 过滤 ----

async def test_list_and_filter(client):
    await client.post("/api/admin/inspiration-entries", json=_create_common())
    await client.post("/api/admin/inspiration-entries", json=_create_product())

    all_rows = await client.get(
        "/api/admin/inspiration-entries", params={"tenant_id": "t1", **_view(OPS)}
    )
    assert all_rows.status_code == 200
    assert len(all_rows.json()) == 2

    common_only = await client.get(
        "/api/admin/inspiration-entries",
        params={"tenant_id": "t1", "layer": "common", **_view(OPS)},
    )
    assert len(common_only.json()) == 1
    assert common_only.json()[0]["layer"] == "common"


async def test_list_requires_view_role(client):
    r = await client.get(
        "/api/admin/inspiration-entries", params={"tenant_id": "t1", **_view(NOBODY)}
    )
    assert r.status_code == 403


# ---- 更新 + 删除 ----

async def test_update_and_delete(client):
    created = await client.post("/api/admin/inspiration-entries", json=_create_common())
    entry_id = created.json()["entry_id"]

    upd = await client.put(
        f"/api/admin/inspiration-entries/{entry_id}",
        json={"content": "改后内容", "enabled": False, "actor": OPS},
    )
    assert upd.status_code == 200
    assert upd.json()["content"] == "改后内容"
    assert upd.json()["enabled"] is False

    deleted = await client.request(
        "DELETE",
        f"/api/admin/inspiration-entries/{entry_id}",
        json={"actor": OPS},
    )
    assert deleted.status_code == 200

    missing = await client.get(
        "/api/admin/inspiration-entries", params={"tenant_id": "t1", **_view(OPS)}
    )
    assert missing.json() == []


async def test_update_missing_returns_404(client):
    r = await client.put(
        "/api/admin/inspiration-entries/nonexistent",
        json={"content": "x", "actor": OPS},
    )
    assert r.status_code == 404


# ---- DIM-SOURCE 上下文查询（服务层，直接走 session）----

async def test_context_for_planning_picks_common_and_product(session_factory):
    async with session_factory() as session:
        session.add(
            InspirationEntry(
                tenant_id="t1",
                layer="common",
                product_space_id=None,
                content="通用 C",
                tags=[],
                enabled=True,
            )
        )
        session.add(
            InspirationEntry(
                tenant_id="t1",
                layer="product",
                product_space_id="ps1",
                content="产品 P",
                tags=[],
                enabled=True,
            )
        )
        # 另一租户的通用条目不应出现
        session.add(
            InspirationEntry(
                tenant_id="t2",
                layer="common",
                product_space_id=None,
                content="其它租户",
                tags=[],
                enabled=True,
            )
        )
        # 同租户但禁用的条目不应出现
        session.add(
            InspirationEntry(
                tenant_id="t1",
                layer="common",
                product_space_id=None,
                content="禁用",
                tags=[],
                enabled=False,
            )
        )
        await session.commit()

        rows = await inspiration_service.get_context_for_planning(
            session, tenant_id="t1", product_space_id="ps1"
        )
        contents = {r.content for r in rows}
        assert contents == {"通用 C", "产品 P"}

        text = inspiration_service.format_inspiration_context(rows)
        assert "通用 C" in text and "产品 P" in text
        assert "其它租户" not in text and "禁用" not in text


async def test_format_empty_context():
    assert inspiration_service.format_inspiration_context([]) == "（无）"
