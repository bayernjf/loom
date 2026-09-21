"""Q160 集成测试：客户批量 Excel（.xlsx）上传 POST /api/effects/backfill/upload-excel。

与 Q156 CSV 上传同契约（02 C1.103，接缝按推荐甲）：
- 客户通道、无 Agent Key；body {tenant_id, content_id, content_base64, filename?,
  actor}，content_base64 为 .xlsx 字节的标准 base64（JSON body 携文本，零 multipart）；
- 服务端 openpyxl 读活动工作表（第一个 sheet），单元格归一化后走与 CSV 完全一致的
  固定 9 列逐行校验，任一文件/表头/行错误整批 422 回 errors[]{index,line,field,
  message}，不入库；
- 全合法才走 Q128 整批 all-or-nothing（只命中本租户非 discarded 成品、绝不孤儿、
  幂等覆盖/异点追加、指标稀疏绝不补 0），回 receipt + 逐行 accepted；
- captured_at 列须为带时区 ISO 文本：Excel 日期单元格是 naive，逐行报错不臆测时区；
  数值计数（100 / 100.0）归一为整数字面量，read_rate 0..1；
- 行数硬上限 settings.backfill_upload_max_rows，超限 422。新依赖 openpyxl、零迁移。
"""

import base64
import datetime as dt
import io
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_DISCARDED, CONTENT_READY, ContentProduct
from app.core.db import Base, get_session, settings
from app.core.effects.models import EffectRecord
from app.main import app

CUSTOMER = {"id": "cust-1", "roles": []}

HEADER = [
    "platform_post_id", "captured_at", "plays", "likes", "comments", "shares",
    "inquiries", "conversions", "read_rate",
]


def _xlsx_b64(rows, *, extra_sheet_header=None) -> str:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    if extra_sheet_header is not None:
        # 多工作表：活动表仍是第一个，额外表不应被读取。
        other = wb.create_sheet("ignored")
        other.append(extra_sheet_header)
    buf = io.BytesIO()
    wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


def _upload(tenant, content_id, content_base64, *, filename=None, actor=CUSTOMER):
    return {
        "tenant_id": tenant, "content_id": content_id,
        "content_base64": content_base64, "filename": filename, "actor": actor,
    }


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
                content_id="c2", tenant_id="t1", product_space_id="ps-1",
                final_id="fcw-2", goal="种草", platform="douyin",
                status=CONTENT_DISCARDED,
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


async def _count(session_factory) -> int:
    async with session_factory() as session:
        return (
            await session.execute(select(func.count()).select_from(EffectRecord))
        ).scalar_one()


# ---------- 主流程 ----------


async def test_excel_happy_path_parses_persists_and_echoes_rows(
    client, session_factory
):
    # 文本 tz 时间 + 数值计数（含整数 float 100.0）+ 稀疏尾部空单元格 + 偏移时区，
    # 且带一个不应被读取的第二工作表。
    rows = [
        HEADER,
        ["https://x/1", "2026-09-01T10:00:00Z", 10, None, None, None, None, None, 0.4],
        ["https://x/2", "2026-09-02T18:30:00+08:00", 25.0, 3, 1, None, None, None, None],
    ]
    r = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", _xlsx_b64(rows, extra_sheet_header=HEADER),
                     filename="batch.xlsx"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["received"] == 2 and body["matched"] == 2
    assert body["orphan"] == 0 and body["upserted"] == 0
    assert body["filename"] == "batch.xlsx"
    assert [row["line"] for row in body["rows"]] == [2, 3]
    assert body["rows"][0]["platform_post_id"] == "https://x/1"

    async with session_factory() as session:
        persisted = list(
            (
                await session.scalars(
                    select(EffectRecord)
                    .where(EffectRecord.external_content_id == "c1")
                    .order_by(EffectRecord.captured_at)
                )
            ).all()
        )
        assert len(persisted) == 2
        # 稀疏纪律：尾部/中间空指标列不落 0；数值计数归一为整数。
        assert persisted[0].metrics == {"plays": 10, "read_rate": 0.4}
        assert persisted[1].metrics == {"plays": 25, "likes": 3, "comments": 1}
        assert all(row.status == "matched" for row in persisted)


async def test_excel_idempotent_overwrite_and_series_append(
    client, session_factory
):
    rows = [HEADER, ["p", "2026-09-01T10:00:00Z", 5, None, None, None, None, None, None]]
    first = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", _xlsx_b64(rows)),
    )
    assert first.json()["upserted"] == 0
    again = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", _xlsx_b64(rows)),
    )
    assert again.json()["upserted"] == 1
    assert await _count(session_factory) == 1

    rows2 = [HEADER, ["p", "2026-09-02T10:00:00Z", 5, None, None, None, None, None, None]]
    third = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", _xlsx_b64(rows2)),
    )
    assert third.json()["upserted"] == 0
    assert await _count(session_factory) == 2


# ---------- 逐行回执（一次性返回全部坏行，整批不落库） ----------


async def test_excel_collects_all_bad_rows_then_422_without_persist(
    client, session_factory
):
    rows = [
        HEADER,
        ["p1", "2026-09-01T10:00:00Z", -1, None, None, None, None, None, None],  # 负计数
        ["p2", dt.datetime(2026, 9, 1, 10, 0), 5, None, None, None, None, None, None],  # noqa: DTZ001  # 故意 naive 日期单元格
        ["", "2026-09-01T10:00:00Z", 5, None, None, None, None, None, None],    # 缺 post_id
        ["p4", "2026-09-01T10:00:00Z", None, None, None, None, None, None, 2],  # rate 越界
        ["p5", "2026-09-01T10:00:00Z", 1.5, None, None, None, None, None, None],  # 计数小数
    ]
    r = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", _xlsx_b64(rows)),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["message"] == "Excel validation failed"
    errors = r.json()["detail"]["errors"]
    fields = {(e["line"], e["field"]) for e in errors}
    assert (2, "metrics.plays") in fields
    assert (3, "captured_at") in fields
    assert (4, "platform_post_id") in fields
    assert (5, "metrics.read_rate") in fields
    assert (6, "metrics.plays") in fields
    assert all("index" in e and "message" in e for e in errors)
    assert await _count(session_factory) == 0


async def test_excel_date_only_cell_rejected(client, session_factory):
    # 纯日期单元格（naive）→ tz-aware 铁律拒绝。
    rows = [HEADER, ["p", dt.date(2026, 9, 1), 1, None, None, None, None, None, None]]
    r = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", _xlsx_b64(rows)),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["field"] == "captured_at"
    assert await _count(session_factory) == 0


# ---------- 表头 / 空工作簿 ----------


async def test_excel_header_and_empty_errors(client, session_factory):
    # 未知列（第 10 列表头）。
    unknown = [HEADER + ["followers"],
               ["p", "2026-09-01T10:00:00Z", 1, None, None, None, None, None, None, 9]]
    r1 = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", _xlsx_b64(unknown)),
    )
    assert r1.status_code == 422
    assert "unknown header column" in r1.json()["detail"]["errors"][0]["message"]

    # 缺 conversions 列。
    missing_header = [c for c in HEADER if c != "conversions"]
    missing = [missing_header,
               ["p", "2026-09-01T10:00:00Z", 1, None, None, None, None, None]]
    r2 = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", _xlsx_b64(missing)),
    )
    assert r2.status_code == 422
    assert r2.json()["detail"]["errors"][0]["field"] == "header"

    # 仅表头无数据。
    header_only = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", _xlsx_b64([HEADER])),
    )
    assert header_only.status_code == 422
    assert header_only.json()["detail"]["errors"][0]["field"] == "rows"
    assert await _count(session_factory) == 0


# ---------- 文件 / base64 级错误 ----------


async def test_excel_invalid_base64_and_non_xlsx_422(client, session_factory):
    # 非法 base64（含字母表外字符）。
    r1 = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", "@@not-base64@@"),
    )
    assert r1.status_code == 422
    err = r1.json()["detail"]["errors"][0]
    assert err["field"] == "file" and "base64" in err["message"]

    # 合法 base64 但内容不是 .xlsx（如纯文本/旧 .xls）。
    r2 = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", base64.b64encode(b"plain text, not xlsx").decode()),
    )
    assert r2.status_code == 422
    assert r2.json()["detail"]["errors"][0]["field"] == "file"
    assert await _count(session_factory) == 0


# ---------- 租户/作废隔离（绝不孤儿） ----------


async def test_excel_unknown_discarded_or_other_tenant_content_422(
    client, session_factory
):
    rows = [HEADER, ["p", "2026-09-01T10:00:00Z", 1, None, None, None, None, None, None]]
    payload = _xlsx_b64(rows)
    for content_id in ("ghost", "c2", "c3"):  # 不存在 / 已作废 / 他租户
        r = await client.post(
            "/api/effects/backfill/upload-excel",
            json=_upload("t1", content_id, payload),
        )
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["field"] == "content_id"
        assert await _count(session_factory) == 0
    assert await _count(session_factory) == 0


# ---------- 行数硬上限 ----------


async def test_excel_row_hard_cap_422(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "backfill_upload_max_rows", 2)
    rows = [HEADER] + [
        [f"p{i}", f"2026-09-0{i+1}T10:00:00Z", 1, None, None, None, None, None, None]
        for i in range(3)
    ]
    r = await client.post(
        "/api/effects/backfill/upload-excel",
        json=_upload("t1", "c1", _xlsx_b64(rows)),
    )
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert any(e["field"] == "rows" and "limit 2" in e["message"] for e in errors)
    assert await _count(session_factory) == 0
