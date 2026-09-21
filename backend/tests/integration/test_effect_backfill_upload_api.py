"""Q156（段13/Q136 服务端化）集成测试：客户批量 CSV 上传 POST /api/effects/backfill/upload。

口径（02 C1.100，接缝按推荐甲）：
- 客户通道、无 Agent Key；body {tenant_id, content_id, csv, filename?, actor}，
  整份 CSV 挂一个成品（同 Q136 前端岛挂内容详情页），表头固定 9 列；
- 服务端标准库 csv 解析（引号转义/BOM/空行），逐行校验，任一结构/行错误整批
  422 回全部坏行明细（errors[]{index,line,field,message}），不入库；
- 全合法才走 Q128 整批 all-or-nothing（只命中本租户非 discarded 成品、绝不孤儿、
  幂等覆盖/异点追加、指标稀疏绝不补 0），回 receipt + 逐行 accepted；
- captured_at 必须带时区（服务端无客户时区，naive/纯日期逐行报错）；
- 行数硬上限 settings.backfill_upload_max_rows，超限 422。零迁移、无新依赖。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_DISCARDED, CONTENT_READY, ContentProduct
from app.core.db import Base, get_session, settings
from app.core.effects.models import EffectRecord
from app.main import app

CUSTOMER = {"id": "cust-1", "roles": []}

HEADER = (
    "platform_post_id,captured_at,plays,likes,comments,shares,"
    "inquiries,conversions,read_rate"
)


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


def _upload(tenant, content_id, csv, *, filename=None, actor=CUSTOMER):
    return {
        "tenant_id": tenant, "content_id": content_id, "csv": csv,
        "filename": filename, "actor": actor,
    }


# ---------- 主流程 ----------


async def test_upload_happy_path_parses_persists_and_echoes_rows(
    client, session_factory
):
    # BOM + 引号转义 + 稀疏指标（空列缺席）+ 纯空行跳过 + 偏移时区。
    csv = (
        "\ufeff" + HEADER + "\n"
        '"https://x/1",2026-09-01T10:00:00Z,10,,,,,,0.4\n'
        "\n"
        "https://x/2,2026-09-02T18:30:00+08:00,25,3,1,,,,\n"
    )
    r = await client.post(
        "/api/effects/backfill/upload",
        json=_upload("t1", "c1", csv, filename="batch.csv"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["received"] == 2 and body["matched"] == 2
    assert body["orphan"] == 0 and body["upserted"] == 0
    assert body["filename"] == "batch.csv"
    assert [row["line"] for row in body["rows"]] == [2, 4]  # 空行不计、物理行号正确
    assert body["rows"][0]["platform_post_id"] == "https://x/1"

    async with session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(EffectRecord)
                    .where(EffectRecord.external_content_id == "c1")
                    .order_by(EffectRecord.captured_at)
                )
            ).all()
        )
        assert len(rows) == 2
        # 稀疏纪律：空指标列不落 0；只保留显式给出的键。
        assert rows[0].metrics == {"plays": 10, "read_rate": 0.4}
        assert rows[1].metrics == {"plays": 25, "likes": 3, "comments": 1}
        assert all(row.status == "matched" for row in rows)


async def test_upload_idempotent_overwrite_and_series_append(client, session_factory):
    csv = HEADER + "\np,2026-09-01T10:00:00Z,5,,,,,,\n"
    first = await client.post(
        "/api/effects/backfill/upload", json=_upload("t1", "c1", csv)
    )
    assert first.json()["upserted"] == 0
    # 同采集点重推 → 覆盖。
    again = await client.post(
        "/api/effects/backfill/upload", json=_upload("t1", "c1", csv)
    )
    assert again.json()["upserted"] == 1
    assert await _count(session_factory) == 1
    # 新采集点 → 追加。
    csv2 = HEADER + "\np,2026-09-02T10:00:00Z,5,,,,,,\n"
    third = await client.post(
        "/api/effects/backfill/upload", json=_upload("t1", "c1", csv2)
    )
    assert third.json()["upserted"] == 0
    assert await _count(session_factory) == 2


# ---------- 逐行回执（一次性返回全部坏行，整批不落库） ----------


async def test_upload_collects_all_bad_rows_then_422_without_persist(
    client, session_factory
):
    csv = (
        HEADER + "\n"
        "p1,2026-09-01T10:00:00Z,-1,,,,,,\n"            # 负计数
        "p2,2026-09-01 10:00:00,5,,,,,,\n"             # naive 时间
        ",2026-09-01T10:00:00Z,5,,,,,,\n"              # 缺 post_id
        "p4,2026-09-01T10:00:00Z,,,,,,,2\n"            # read_rate 越界
        "p5,2026-09-01T10:00:00Z,1,2\n"                # 列数不符
    )
    r = await client.post(
        "/api/effects/backfill/upload", json=_upload("t1", "c1", csv)
    )
    assert r.status_code == 422, r.text
    errors = r.json()["detail"]["errors"]
    fields = {(e["line"], e["field"]) for e in errors}
    assert (2, "metrics.plays") in fields
    assert (3, "captured_at") in fields
    assert (4, "platform_post_id") in fields
    assert (5, "metrics.read_rate") in fields
    assert (6, "columns") in fields
    # 所有错误都带数据行 0 基 index 与物理行号。
    assert all("index" in e and "message" in e for e in errors)
    assert await _count(session_factory) == 0


async def test_upload_naive_date_only_rejected(client, session_factory):
    csv = HEADER + "\np,2026-09-01,5,,,,,,\n"  # 纯日期＝naive
    r = await client.post(
        "/api/effects/backfill/upload", json=_upload("t1", "c1", csv)
    )
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["field"] == "captured_at"
    assert await _count(session_factory) == 0


# ---------- 表头 / 空文件 ----------


async def test_upload_header_errors(client, session_factory):
    # 缺 read_rate 列
    missing = (
        "platform_post_id,captured_at,plays,likes,comments,shares,"
        "inquiries,conversions\n"
        "p,2026-09-01T10:00:00Z,1,,,,,,\n"
    )
    r1 = await client.post(
        "/api/effects/backfill/upload", json=_upload("t1", "c1", missing)
    )
    assert r1.status_code == 422
    assert r1.json()["detail"]["errors"][0]["field"] == "header"

    # 未知列
    unknown = HEADER.replace("read_rate", "followers")
    r2 = await client.post(
        "/api/effects/backfill/upload", json=_upload("t1", "c1", unknown + "\n")
    )
    assert r2.status_code == 422
    assert "unknown header column" in r2.json()["detail"]["errors"][0]["message"]

    # 空文件 / 仅表头无数据
    assert (await client.post(
        "/api/effects/backfill/upload", json=_upload("t1", "c1", "   ")
    )).status_code == 422
    header_only = await client.post(
        "/api/effects/backfill/upload",
        json=_upload("t1", "c1", HEADER + "\n"),
    )
    assert header_only.status_code == 422
    assert header_only.json()["detail"]["errors"][0]["field"] == "rows"
    assert await _count(session_factory) == 0


# ---------- 租户/作废隔离（绝不孤儿） ----------


async def test_upload_unknown_discarded_or_other_tenant_content_422(
    client, session_factory
):
    csv = HEADER + "\np,2026-09-01T10:00:00Z,1,,,,,,\n"
    for content_id in ("ghost", "c2", "c3"):  # 不存在 / 已作废 / 他租户
        r = await client.post(
            "/api/effects/backfill/upload",
            json=_upload("t1", content_id, csv),
        )
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["field"] == "content_id"
        assert await _count(session_factory) == 0
    assert await _count(session_factory) == 0


# ---------- 行数硬上限 ----------


async def test_upload_row_hard_cap_422(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "backfill_upload_max_rows", 2)
    csv = HEADER + "".join(
        f"\np{i},2026-09-0{i+1}T10:00:00Z,1,,,,,,\n" for i in range(3)
    )
    r = await client.post(
        "/api/effects/backfill/upload", json=_upload("t1", "c1", csv)
    )
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert any(e["field"] == "rows" and "limit 2" in e["message"] for e in errors)
    assert await _count(session_factory) == 0
