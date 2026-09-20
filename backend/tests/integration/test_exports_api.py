from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
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


# ---------- Q132：JSON 形态与导出任务 ----------


async def test_json_export_empty_for_unknown_tenant(client):
    # 与 CSV 同口径：未知租户返回空 envelope 200，不 404。
    r = await client.get("/api/exports/fcw.json", params={"tenant_id": "ghost"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "attachment" in r.headers["content-disposition"]
    assert r.json() == {
        "tenant_id": "ghost",
        "product_space_id": None,
        "count": 0,
        "final_ids": [],
    }


async def test_json_export_published_only_scoped(client, session_factory):
    async with session_factory() as session:
        session.add(
            Tenant(tenant_id="t2", name="第二客户", plan="basic", status="active")
        )
        session.add_all(
            [
                _fcw("t1", "ps-1", 11),
                _fcw("t1", "ps-1", 12, status=PUBLISH_DRAFT),
                _fcw("t2", "ps-9", 13),
            ]
        )
        await session.commit()

    r = await client.get("/api/exports/fcw.json", params={"tenant_id": "t1"})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1  # draft 与 t2 均排除

    r = await client.get(
        "/api/exports/fcw.json",
        params={"tenant_id": "t1", "product_space_id": "ps-1"},
    )
    assert r.json()["count"] == 1


async def test_json_export_rejects_empty_tenant(client):
    r = await client.get("/api/exports/fcw.json", params={"tenant_id": ""})
    assert r.status_code == 422


async def test_create_csv_job_completed_and_download_matches(client, session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                _fcw("t1", "ps-1", 21),
                _fcw("t1", "ps-1", 22, status=PUBLISH_DRAFT),
            ]
        )
        await session.commit()

    r = await client.post(
        "/api/exports/jobs",
        json={"tenant_id": "t1", "format": "csv", "actor": {"id": "mg-1"}},
    )
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "completed"
    assert job["row_count"] == 1
    assert job["format"] == "csv"
    assert job["file_name"] == "fcw-t1.csv"
    assert job["completed_at"] is not None
    assert job["download_url"] == f"/api/exports/jobs/{job['job_id']}/download"

    d = await client.get(job["download_url"])
    assert d.status_code == 200
    assert d.headers["content-type"].startswith("text/csv")
    sync = await client.get("/api/exports/fcw.csv", params={"tenant_id": "t1"})
    assert d.text == sync.text


async def test_create_json_job_download_matches_json_endpoint(
    client, session_factory
):
    async with session_factory() as session:
        session.add(_fcw("t1", "ps-1", 23))
        await session.commit()

    r = await client.post(
        "/api/exports/jobs",
        json={
            "tenant_id": "t1",
            "product_space_id": "ps-1",
            "format": "json",
            "actor": {"id": "mg-1"},
        },
    )
    job = r.json()
    assert job["file_name"] == "fcw-t1.json"
    d = await client.get(job["download_url"])
    assert d.headers["content-type"].startswith("application/json")
    sync = await client.get(
        "/api/exports/fcw.json",
        params={"tenant_id": "t1", "product_space_id": "ps-1"},
    )
    assert d.json() == sync.json()


async def test_create_job_defaults_to_csv(client):
    r = await client.post(
        "/api/exports/jobs",
        json={"tenant_id": "ghost", "actor": {"id": "mg-1"}},
    )
    assert r.status_code == 201
    job = r.json()
    assert job["format"] == "csv"
    assert job["row_count"] == 0
    assert job["status"] == "completed"


async def test_create_job_rejects_bad_format_missing_actor_empty_tenant(client):
    r = await client.post(
        "/api/exports/jobs",
        json={"tenant_id": "t1", "format": "xml", "actor": {"id": "mg-1"}},
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/exports/jobs", json={"tenant_id": "t1", "format": "csv"}
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/exports/jobs",
        json={"tenant_id": "", "format": "csv", "actor": {"id": "mg-1"}},
    )
    assert r.status_code == 422


async def test_unknown_job_404_for_status_and_download(client):
    r = await client.get("/api/exports/jobs/nope")
    assert r.status_code == 404
    r = await client.get("/api/exports/jobs/nope/download")
    assert r.status_code == 404


async def test_job_download_rerenders_current_data(client, session_factory):
    # 下载按任务参数重渲染：创建后新发证，下载体反映当前集合（幂等不存 payload）；
    # 任务记录 row_count 为创建时留痕，不随后续数据变化。
    r = await client.post(
        "/api/exports/jobs",
        json={"tenant_id": "t1", "actor": {"id": "mg-1"}},
    )
    job = r.json()
    assert job["row_count"] == 0

    async with session_factory() as session:
        session.add(_fcw("t1", "ps-1", 24))
        await session.commit()

    d = await client.get(job["download_url"])
    lines = d.text.splitlines()
    assert lines[0] == "final_id"
    assert len(lines) == 2  # 表头 + 新发证一条

    again = await client.get(f"/api/exports/jobs/{job['job_id']}")
    assert again.json()["row_count"] == 0


async def test_job_creation_writes_audit(client, session_factory):
    async with session_factory() as session:
        session.add(_fcw("t1", "ps-1", 25))
        await session.commit()

    r = await client.post(
        "/api/exports/jobs",
        json={"tenant_id": "t1", "format": "json", "actor": {"id": "mg-7"}},
    )
    job_id = r.json()["job_id"]

    async with session_factory() as session:
        logs = list(
            (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "export.job_created"
                    )
                )
            ).all()
        )
    assert len(logs) == 1
    assert logs[0].tenant_id == "t1"
    assert logs[0].actor_id == "mg-7"
    assert logs[0].entity_type == "export_job"
    assert logs[0].entity_id == job_id
    assert logs[0].detail["format"] == "json"
    assert logs[0].detail["row_count"] == 1
