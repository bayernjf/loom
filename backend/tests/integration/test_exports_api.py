from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.tenants.models import Tenant
from app.final.final_whitelist.models import (
    PUBLISH_DRAFT,
    FinalContentWhitelist,
)
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
    async with session_factory() as session:
        session.add(Tenant(tenant_id="t1", name="试点客户", plan="basic", status="active"))
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _fcw(
    tenant_id: str,
    product_space_id: str,
    seq: int,
    *,
    status: str | None = None,
) -> FinalContentWhitelist:
    # seq 分化 uq_fcw_same_issue(pws_id, pwc_id, platform, slot_id) 唯一键。
    kwargs: dict[str, str | bool] = {
        "tenant_id": tenant_id,
        "product_space_id": product_space_id,
        "pws_id": f"pws-{seq}",
        "pwc_id": f"pwc-{seq}",
        "pcp_id": "pcp-1",
        "csp_package_id": "csp-1",
        "cstp_package_id": "cstp-1",
        "cep_package_id": "cep-1",
        "platform": "xhs",
        "slot_id": f"slot-{seq}",
        "goal": "ENGAGEMENT",
        "guards_passed": True,
        "issued_by": "ops-1",
    }
    if status is not None:
        kwargs["publish_status"] = status
    return FinalContentWhitelist(**kwargs)


async def test_export_header_only_for_unknown_tenant(client):
    # Q100：读路径不触发 Q95 准入门，未知租户=仅表头空文件 200。
    r = await client.get("/api/exports/fcw.csv", params={"tenant_id": "ghost"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text == "final_id\n"


async def test_export_published_only_scoped(client, session_factory):
    async with session_factory() as session:
        session.add(Tenant(tenant_id="t2", name="第二客户", plan="basic", status="active"))
        session.add_all(
            [
                _fcw("t1", "ps-1", 1),
                _fcw("t1", "ps-1", 2),
                _fcw("t1", "ps-1", 3, status=PUBLISH_DRAFT),
                _fcw("t1", "ps-other", 4),
                _fcw("t2", "ps-9", 5),
            ]
        )
        await session.commit()

    r = await client.get("/api/exports/fcw.csv", params={"tenant_id": "t1"})
    assert r.status_code == 200
    lines = r.text.splitlines()
    assert lines[0] == "final_id"
    assert len(lines) == 4  # 表头 + t1 三条 published（draft 与 t2 均排除）

    # 严格单列：每行恰好一个 final_id，无逗号即无上下文字段。
    exported = lines[1:]
    assert all("," not in row for row in exported)

    async with session_factory() as session:
        expected = list(
            (
                await session.scalars(
                    select(FinalContentWhitelist.final_id).where(
                        FinalContentWhitelist.tenant_id == "t1",
                        FinalContentWhitelist.publish_status == "published",
                    )
                )
            ).all()
        )
    assert sorted(exported) == sorted(expected)

    r = await client.get(
        "/api/exports/fcw.csv",
        params={"tenant_id": "t1", "product_space_id": "ps-other"},
    )
    narrow = r.text.splitlines()
    assert narrow[0] == "final_id"
    assert len(narrow) == 2
    async with session_factory() as session:
        expected_narrow = list(
            (
                await session.scalars(
                    select(FinalContentWhitelist.final_id).where(
                        FinalContentWhitelist.tenant_id == "t1",
                        FinalContentWhitelist.product_space_id == "ps-other",
                    )
                )
            ).all()
        )
    assert narrow[1] == expected_narrow[0]


async def test_export_rejects_empty_tenant(client):
    r = await client.get("/api/exports/fcw.csv", params={"tenant_id": ""})
    assert r.status_code == 422
