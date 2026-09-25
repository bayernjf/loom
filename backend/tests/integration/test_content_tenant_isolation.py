"""Q200 #32 集成测试：客户内容详情/裁决/正文改写/intake 语言口的租户归属收口。

探针证据（Q199 §7.2，修复前必红）：tenant-B 以 query ``tenant_id=tenant-B`` 读
tenant-A 的成品返回 200、approve 返回 200 且把 A 侧状态改成 ready_for_publish。
本文件把这些断言固化：跨租户统一 404（与 #31 导出口口径一致，不提供存在性探针）、
缺 tenant_id 422、同租户行为 200 不变。
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_REVIEW, ContentLanguage, ContentProduct
from app.core.db import Base, get_session
from app.main import app
from app.product.product_intake.models import ProductSpace

CUSTOMER_B = {"id": "cust-B", "roles": []}
CUSTOMER_A = {"id": "cust-A", "roles": []}


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
            # tenant-A 的受害成品（review 态，可被裁决/改写）。
            ContentProduct(
                content_id="victim-1",
                tenant_id="tenant-A",
                product_space_id="ps-A",
                final_id="fcw-A",
                goal="种草",
                platform="douyin",
                status=CONTENT_REVIEW,
            ),
            # tenant-B 自己的成品（证明 404 是归属拦截而非"不存在"）。
            ContentProduct(
                content_id="own-1",
                tenant_id="tenant-B",
                product_space_id="ps-B",
                final_id="fcw-B",
                goal="种草",
                platform="douyin",
                status=CONTENT_REVIEW,
            ),
            ProductSpace(
                product_space_id="ps-A", tenant_id="tenant-A", intake_id="int-A"
            ),
            ProductSpace(
                product_space_id="ps-B", tenant_id="tenant-B", intake_id="int-B"
            ),
        ])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_cross_tenant_read_is_404(client):
    # tenant-B 声明自己的租户读 tenant-A 的成品 → 404（此前 200 + 返回体 tenant_id=tenant-A）。
    r = await client.get(
        "/api/content/victim-1", params={"tenant_id": "tenant-B"}
    )
    assert r.status_code == 404, r.text

    # 对照：tenant-B 读自己的成品 → 200 不变。
    r = await client.get("/api/content/own-1", params={"tenant_id": "tenant-B"})
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == "tenant-B"


async def test_cross_tenant_approve_is_404(client):
    # tenant-B 裁决 tenant-A 的成品 → 404（此前 200 且把 A 侧状态改掉）。
    r = await client.post(
        "/api/content/victim-1/approve",
        params={"tenant_id": "tenant-B"},
        json={"actor": CUSTOMER_B},
    )
    assert r.status_code == 404, r.text

    # 后果：tenant-A 侧状态仍是 review，未被改动（此前变成 ready_for_publish）。
    r = await client.get(
        "/api/content/victim-1", params={"tenant_id": "tenant-A"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == CONTENT_REVIEW


async def test_cross_tenant_reject_and_revise_are_404(client):
    for suffix in ("reject", "revise"):
        payload = {"actor": CUSTOMER_B}
        if suffix == "reject":
            payload["reason"] = "串台"
        r = await client.post(
            f"/api/content/victim-1/{suffix}",
            params={"tenant_id": "tenant-B"},
            json=payload,
        )
        assert r.status_code == 404, f"{suffix}: {r.text}"


async def test_cross_tenant_body_edit_is_404(client):
    r = await client.patch(
        "/api/content/victim-1/body",
        params={"tenant_id": "tenant-B"},
        json={"body": "越权改写", "actor": CUSTOMER_B},
    )
    assert r.status_code == 404, r.text


async def test_missing_tenant_id_is_422(client):
    # 客户口必须显式声明租户（否则"不传就穿透"仍是缺陷）。
    r = await client.get("/api/content/victim-1")
    assert r.status_code == 422, r.text
    r = await client.post(
        "/api/content/victim-1/approve", json={"actor": CUSTOMER_B}
    )
    assert r.status_code == 422, r.text


async def test_same_tenant_read_and_adjudicate_unchanged(client):
    r = await client.get(
        "/api/content/victim-1", params={"tenant_id": "tenant-A"}
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        "/api/content/victim-1/approve",
        params={"tenant_id": "tenant-A"},
        json={"actor": CUSTOMER_A},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready_for_publish"


async def test_intake_target_languages_cross_tenant_404(client):
    # tenant-B 改 tenant-A 的产品空间语言 → 404（此前仅代码级确认无租户条件）。
    r = await client.patch(
        "/api/intakes/int-A/target-languages",
        params={"tenant_id": "tenant-B"},
        json={"languages": ["zh-CN"], "actor": CUSTOMER_B},
    )
    assert r.status_code == 404, r.text

    # 对照：tenant-A 改自己的 → 200 不变。
    r = await client.patch(
        "/api/intakes/int-A/target-languages",
        params={"tenant_id": "tenant-A"},
        json={"languages": ["zh-CN"], "actor": CUSTOMER_A},
    )
    assert r.status_code == 200, r.text
    assert r.json()["target_languages"] == ["zh-CN"]
