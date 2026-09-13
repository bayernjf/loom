from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import G2Field


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


@pytest_asyncio.fixture
async def seeded_common_fields(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                G2Field(fid="f_name", cat="common", field_name="产品名"),
                G2Field(fid="f_brief", cat="common", field_name="简介"),
                G2Field(fid="x_deprecated", cat="common", field_name="废弃字段",
                        status="deprecated"),
            ]
        )
        await session.commit()


OPS = {"id": "ops-1", "roles": ["operations"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


async def _fire(client, intake_id, event, actor=OPS, **extra):
    return await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": event, "actor": actor, **extra},
    )


async def test_submit_blocked_when_common_fields_missing(client, seeded_common_fields):
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t1", "profile": {"f_name": "面霜"}}
    )
    assert r.status_code == 201
    intake_id = r.json()["intake_id"]

    r = await _fire(client, intake_id, "submit", actor=CUSTOMER)
    assert r.status_code == 422
    assert r.json()["detail"]["missing_fids"] == ["f_brief"]


async def test_full_flow_creates_ps_snapshot(client, seeded_common_fields):
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t1", "profile": {"f_name": "面霜"}}
    )
    intake_id = r.json()["intake_id"]

    r = await client.patch(
        f"/api/intakes/{intake_id}/profile",
        json={"profile": {"f_brief": "保湿修护"}, "actor": CUSTOMER},
    )
    assert r.status_code == 200

    for event, actor in [
        ("submit", CUSTOMER),
        ("wf01_confirm", OPS),
        ("ops_confirm", OPS),
        ("send_review", OPS),
        ("review_approve", OPS),
        ("start_modeling", OPS),
        ("model_stored", OPS),
    ]:
        r = await _fire(client, intake_id, event, actor=actor)
        assert r.status_code == 200, (event, r.text)
    assert r.json()["status"] == sm.STORED

    r = await client.get(f"/api/intakes/{intake_id}/product-space")
    assert r.status_code == 200
    body = r.json()
    assert body["lifecycle"] == sm.MODELING
    assert body["profile_snapshot"] == {"f_name": "面霜", "f_brief": "保湿修护"}

    # 入库后资料不可改（Q74 快照纪律）。
    r = await client.patch(
        f"/api/intakes/{intake_id}/profile",
        json={"profile": {"f_name": "篡改"}, "actor": CUSTOMER},
    )
    assert r.status_code == 409


async def test_terminal_and_role_guards(client, seeded_common_fields):
    r = await client.post(
        "/api/intakes",
        json={
            "tenant_id": "t1",
            "profile": {"f_name": "x", "f_brief": "y"},
        },
    )
    intake_id = r.json()["intake_id"]
    await _fire(client, intake_id, "submit", actor=CUSTOMER)
    await _fire(client, intake_id, "wf01_confirm", actor=OPS)

    # 类目确认必须运营（Q3）。
    r = await _fire(client, intake_id, "ops_confirm", actor=CUSTOMER)
    assert r.status_code == 403

    await _fire(client, intake_id, "ops_confirm", actor=OPS)
    await _fire(client, intake_id, "send_review", actor=OPS)
    await _fire(client, intake_id, "review_reject", actor=OPS)

    r = await _fire(client, intake_id, "submit", actor=CUSTOMER)
    assert r.status_code == 409  # 驳回终态
