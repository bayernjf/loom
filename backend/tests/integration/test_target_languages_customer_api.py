"""B3/Q122 集成测试：客户目标语言录入控件后端。

- GET /api/content/languages：客户只读 active 语言清单（无闸、不含归档）；
- PATCH /api/intakes/{id}/target-languages：客户口径（roles 恒空可调），
  按 intake 定位产品空间，校验 active 码 / 去重，回写 ProductSpaceView；
- Q119 operations PUT /api/product-spaces/{id}/target-languages 的 OPERATIONS
  角色闸保持不变（客户 roles 空仍 403）。
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import ContentLanguage
from app.core.db import Base, get_session
from app.main import app
from app.product.product_intake.models import ProductSpace

OPS = {"id": "ops-1", "roles": ["operations"]}
CUSTOMER = {"id": "cust-1", "roles": []}


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    async with maker() as session:
        session.add_all([
            ContentLanguage(code="zh-CN", name="简体中文", markets=[], status="active"),
            ContentLanguage(code="en-US", name="English", markets=[], status="active"),
            ContentLanguage(code="fr-FR", name="Français", markets=[], status="archived"),
            ProductSpace(
                product_space_id="ps-1", tenant_id="t1", intake_id="int-1"
            ),
        ])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_active_language_catalog_is_open_and_excludes_archived(client):
    r = await client.get("/api/content/languages")
    assert r.status_code == 200, r.text
    codes = [row["code"] for row in r.json()]
    assert codes == ["en-US", "zh-CN"]  # code 排序，fr-FR 归档不返
    assert all(row["status"] == "active" for row in r.json())


async def test_customer_sets_target_languages_and_space_view_echoes(client):
    r = await client.patch(
        "/api/intakes/int-1/target-languages?tenant_id=t1",
        json={"languages": ["zh-CN", "en-US"], "actor": CUSTOMER},
    )
    assert r.status_code == 200, r.text
    assert r.json()["target_languages"] == ["zh-CN", "en-US"]

    r = await client.get("/api/intakes/int-1/product-space")
    assert r.status_code == 200, r.text
    assert r.json()["target_languages"] == ["zh-CN", "en-US"]


async def test_empty_languages_clears_to_null(client):
    r = await client.patch(
        "/api/intakes/int-1/target-languages?tenant_id=t1",
        json={"languages": [], "actor": CUSTOMER},
    )
    assert r.status_code == 200, r.text
    assert r.json()["target_languages"] is None


async def test_invalid_language_codes_422(client):
    # 未知码
    r = await client.patch(
        "/api/intakes/int-1/target-languages?tenant_id=t1",
        json={"languages": ["xx-XX"], "actor": CUSTOMER},
    )
    assert r.status_code == 422, r.text
    # 归档码不可选
    r = await client.patch(
        "/api/intakes/int-1/target-languages?tenant_id=t1",
        json={"languages": ["fr-FR"], "actor": CUSTOMER},
    )
    assert r.status_code == 422, r.text
    # 重复码
    r = await client.patch(
        "/api/intakes/int-1/target-languages?tenant_id=t1",
        json={"languages": ["zh-CN", "zh-CN"], "actor": CUSTOMER},
    )
    assert r.status_code == 422, r.text


async def test_patch_without_product_space_404(client):
    r = await client.patch(
        "/api/intakes/int-ghost/target-languages?tenant_id=t1",
        json={"languages": ["zh-CN"], "actor": CUSTOMER},
    )
    assert r.status_code == 404, r.text


async def test_operations_put_still_gated_for_customers(client):
    # Q119 运营代设入口角色闸不放松：客户 roles 空 → 403。
    r = await client.put(
        "/api/product-spaces/ps-1/target-languages",
        json={"languages": ["zh-CN"], "actor": CUSTOMER},
    )
    assert r.status_code == 403, r.text
    # operations 仍可用。
    r = await client.put(
        "/api/product-spaces/ps-1/target-languages",
        json={"languages": ["en-US"], "actor": OPS},
    )
    assert r.status_code == 200, r.text
    assert r.json()["target_languages"] == ["en-US"]
