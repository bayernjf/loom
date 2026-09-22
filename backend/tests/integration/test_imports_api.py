"""Q161 导入任务端点集成测试（POST /api/effects/backfill/jobs + GET 列表/详情）。

门控关闭（V1 默认）：POST 先落 queued 再请求内同步跑到终态，201 回 completed/
failed 视图（确定性校验失败的逐行错误在 errors，不抛 5xx、不入死信）；门控开启：
POST 回 queued 并 XADD 入导入流，Redis 故障 fail-closed 置 failed 回 503。
内存 SQLite + FakeStreamsRedis，无真 Redis / 无迁移。
"""

import base64
import io
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_READY, ContentProduct
from app.core.config import get_settings
from app.core.db import Base, get_session
from app.core.effects.models import EffectRecord
from app.core.imports import service
from app.core.imports.models import ImportJob
from app.core.queue import override_stream_client
from app.main import app
from tests.integration.stream_fakes import FakeStreamsRedis

CUSTOMER = {"id": "cust-1", "roles": []}
HEADER = [
    "platform_post_id", "captured_at", "plays", "likes", "comments", "shares",
    "inquiries", "conversions", "read_rate",
]
CSV_TWO_ROWS = (
    ",".join(HEADER) + "\n"
    "p1,2026-09-01T10:00:00Z,100,10,1,0,0,0,0.5\n"
    "p2,2026-09-01T12:00:00+08:00,200,,,,,,\n"
)


def _xlsx_b64(rows) -> str:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


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
        session.add_all([
            ContentProduct(
                content_id="c1", tenant_id="t1", product_space_id="ps-1",
                final_id="fcw-1", goal="种草", platform="douyin",
                status=CONTENT_READY,
            ),
            ContentProduct(
                content_id="c3", tenant_id="t2", product_space_id="ps-2",
                final_id="fcw-3", goal="种草", platform="douyin",
                status=CONTENT_READY,
            ),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _csv_body(content_id="c1", tenant="t1", csv_text=CSV_TWO_ROWS, filename="b.csv"):
    return {
        "tenant_id": tenant, "content_id": content_id, "format": "csv",
        "csv": csv_text, "filename": filename, "actor": CUSTOMER,
    }


# ---------- 门控关闭（默认）：请求内同步到终态 ----------

async def test_sync_csv_completes(client, session_factory):
    r = await client.post("/api/effects/backfill/jobs", json=_csv_body())
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "completed"
    assert job["format"] == "csv"
    assert job["received"] == 2
    assert job["matched"] == 2
    assert job["orphan"] == 0
    # 全新行：matched=2，upserted（幂等覆盖已存在行）首次为 0。
    assert job["upserted"] == 0
    assert job["row_count"] == 2
    assert job["completed_at"] is not None
    assert job["errors"] is None

    async with session_factory() as session:
        records = list((await session.scalars(select(EffectRecord))).all())
    assert len(records) == 2


async def test_sync_xlsx_completes(client, session_factory):
    body = {
        "tenant_id": "t1", "content_id": "c1", "format": "xlsx",
        "content_base64": _xlsx_b64(
            [HEADER, ["p1", "2026-09-01T10:00:00Z", 100, 10]]
        ),
        "filename": "b.xlsx", "actor": CUSTOMER,
    }
    r = await client.post("/api/effects/backfill/jobs", json=body)
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "completed"
    assert job["matched"] == 1


async def test_sync_validation_failure_returns_failed_job_with_errors(client, session_factory):
    # read_rate=2 越界：确定性逐行错误，任务 failed（201，任务已建并终态），零落库。
    bad = (
        ",".join(HEADER) + "\n"
        "p1,2026-09-01T10:00:00Z,100,,,,,,2\n"
    )
    r = await client.post("/api/effects/backfill/jobs", json=_csv_body(csv_text=bad))
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "failed"
    assert job["errors"] and isinstance(job["errors"], list)
    assert job["received"] == 0
    async with session_factory() as session:
        records = list((await session.scalars(select(EffectRecord))).all())
    assert records == []


async def test_unknown_content_fails_without_orphan(client):
    r = await client.post("/api/effects/backfill/jobs", json=_csv_body(content_id="nope"))
    assert r.status_code == 201
    assert r.json()["status"] == "failed"


async def test_carrier_payload_mismatch_is_422(client):
    # format=csv 却不给 csv；format=xlsx 却不给 content_base64。
    r1 = await client.post(
        "/api/effects/backfill/jobs",
        json={"tenant_id": "t1", "content_id": "c1", "format": "csv", "actor": CUSTOMER},
    )
    assert r1.status_code == 422
    r2 = await client.post(
        "/api/effects/backfill/jobs",
        json={"tenant_id": "t1", "content_id": "c1", "format": "xlsx", "actor": CUSTOMER},
    )
    assert r2.status_code == 422


async def test_list_and_detail_scoped_to_tenant_and_content(client):
    assert (await client.post("/api/effects/backfill/jobs", json=_csv_body())).status_code == 201
    assert (
        await client.post(
            "/api/effects/backfill/jobs", json=_csv_body(content_id="c3", tenant="t2")
        )
    ).status_code == 201

    lr = await client.get(
        "/api/effects/backfill/jobs", params={"tenant_id": "t1", "content_id": "c1"}
    )
    assert lr.status_code == 200
    payload = lr.json()
    assert payload["count"] == 1
    assert payload["jobs"][0]["content_id"] == "c1"

    all_t1 = await client.get("/api/effects/backfill/jobs", params={"tenant_id": "t1"})
    assert all_t1.json()["count"] == 1

    job_id = payload["jobs"][0]["job_id"]
    ok = await client.get(
        f"/api/effects/backfill/jobs/{job_id}", params={"tenant_id": "t1"}
    )
    assert ok.status_code == 200
    # 租户隔离：t2 查 t1 的任务 404。
    cross = await client.get(
        f"/api/effects/backfill/jobs/{job_id}", params={"tenant_id": "t2"}
    )
    assert cross.status_code == 404


# ---------- 门控开启：queued + 入流 / fail-closed ----------


@pytest_asyncio.fixture
def async_imports(monkeypatch: pytest.MonkeyPatch):
    fake = FakeStreamsRedis()
    override_stream_client(fake)
    monkeypatch.setattr(get_settings(), "import_worker_enabled", True)
    yield fake
    override_stream_client(None)


async def test_async_post_enqueues_queued_job_with_payload(
    client, session_factory, async_imports
):
    r = await client.post("/api/effects/backfill/jobs", json=_csv_body())
    assert r.status_code == 201
    job = r.json()
    job_id = job["job_id"]
    assert job["status"] == "queued"
    assert job["completed_at"] is None

    # payload 已原样落库（后台可重放），消息只携带 job_id 并入导入流。
    async with session_factory() as session:
        row = await service.get_job(session, job_id)
        assert row.payload == CSV_TWO_ROWS
    entries = async_imports.streams[service.IMPORT_STREAM]
    assert any(fields["job_id"] == job_id for _, fields in entries)


async def test_async_enqueue_failure_marks_job_failed_503(
    client, session_factory, monkeypatch: pytest.MonkeyPatch
):
    failing = FakeStreamsRedis(fail=True)
    override_stream_client(failing)
    monkeypatch.setattr(get_settings(), "import_worker_enabled", True)
    try:
        r = await client.post("/api/effects/backfill/jobs", json=_csv_body())
        assert r.status_code == 503
    finally:
        override_stream_client(None)

    async with session_factory() as session:
        jobs = list((await session.scalars(select(ImportJob))).all())
    assert len(jobs) == 1
    assert jobs[0].status == "failed"
    assert "stream backend unavailable" in (jobs[0].error or "")
