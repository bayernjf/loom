"""Q166 集成测试：客户效果数据分析只读聚合 GET /api/effects/analytics。

口径（无闸客户读，同 Q101/Q162）：
- tenant_id 必填 query 收窄，未知租户 200 空（不触发准入门、不写审计）；
- 只统计 status=matched 且 tenant_id 命中的记录（孤儿属运营面、他租户不串）；
- metrics 七键稀疏：六计数按存在键累加（缺席不补 0）；read_rate 为比率不可
  求和，仅对含该键记录取平均（read_rate_samples 为分母）；
- 可选 date_from/date_to（YYYY-MM-DD，date_to 含当天），from>to 返 422。

create_all 不跑迁移种子；成品与效果记录由本文件 fixture 自插。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_READY, ContentProduct
from app.core.db import Base, get_session
from app.core.effects.models import (
    STATUS_MATCHED,
    STATUS_ORPHAN,
    EffectRecord,
)
from app.main import app


def _dt(day: int) -> datetime:
    return datetime(2026, 9, day, 10, 0, tzinfo=UTC)


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
                status=CONTENT_READY,
            ),
            ContentProduct(
                content_id="c3", tenant_id="t2", product_space_id="ps-2",
                final_id="fcw-3", goal="种草", platform="douyin",
                status=CONTENT_READY,
            ),
        ])
        await session.commit()
        session.add_all([
            # t1 / c1：两个采集点（稀疏指标 + read_rate 两样本）。
            EffectRecord(
                source="customer-backfill", external_content_id="c1",
                matched_content_id="c1", tenant_id="t1",
                platform_post_id="https://x/1", captured_at=_dt(1),
                metrics={"plays": 10, "likes": 2, "read_rate": 0.4},
                status=STATUS_MATCHED, received_by="cust-1",
            ),
            EffectRecord(
                source="customer-backfill", external_content_id="c1",
                matched_content_id="c1", tenant_id="t1",
                platform_post_id="https://x/1", captured_at=_dt(3),
                metrics={"plays": 20, "comments": 1, "read_rate": 0.6},
                status=STATUS_MATCHED, received_by="cust-1",
            ),
            # t1 / c2：单采集点，仅 plays（验证稀疏不补 0）。
            EffectRecord(
                source="customer-backfill", external_content_id="c2",
                matched_content_id="c2", tenant_id="t1",
                platform_post_id="https://x/2", captured_at=_dt(2),
                metrics={"plays": 5},
                status=STATUS_MATCHED, received_by="cust-1",
            ),
            # t2 / c3：他租户高播放，不得串入 t1。
            EffectRecord(
                source="customer-backfill", external_content_id="c3",
                matched_content_id="c3", tenant_id="t2",
                platform_post_id="https://x/3", captured_at=_dt(2),
                metrics={"plays": 999},
                status=STATUS_MATCHED, received_by="cust-2",
            ),
            # t1 孤儿：对不上成品，不进客户聚合。
            EffectRecord(
                source="agent", external_content_id="ghost-1",
                matched_content_id=None, tenant_id=None,
                platform_post_id="https://x/g", captured_at=_dt(2),
                metrics={"plays": 777},
                status=STATUS_ORPHAN, received_by="key-1",
            ),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_analytics_unknown_tenant_is_empty(client):
    r = await client.get("/api/effects/analytics", params={"tenant_id": "nope"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "nope"
    assert body["records_total"] == 0
    assert body["contents_covered"] == 0
    assert body["metrics_totals"] == {
        "plays": 0, "likes": 0, "comments": 0, "shares": 0,
        "inquiries": 0, "conversions": 0,
    }
    assert body["read_rate_avg"] is None
    assert body["read_rate_samples"] == 0
    assert body["by_content"] == []
    assert body["captured_from"] is None
    assert body["captured_to"] is None
    assert body["truncated"] is False


async def test_analytics_aggregates_matched_sparse_metrics(client):
    r = await client.get("/api/effects/analytics", params={"tenant_id": "t1"})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["records_total"] == 3
    assert body["contents_covered"] == 2
    # 六计数稀疏合计（缺席键不补 0，但合计视图从 0 起累加存在值）。
    assert body["metrics_totals"] == {
        "plays": 35, "likes": 2, "comments": 1, "shares": 0,
        "inquiries": 0, "conversions": 0,
    }
    # read_rate 仅对两样本取平均（0.4 与 0.6），plays 等不参与。
    assert body["read_rate_avg"] == 0.5
    assert body["read_rate_samples"] == 2
    assert body["captured_from"].startswith("2026-09-01")
    assert body["captured_to"].startswith("2026-09-03")

    # by_content 按 plays 降序：c1(30, 2 条) 先于 c2(5, 1 条)。
    by_content = body["by_content"]
    assert [row["content_id"] for row in by_content] == ["c1", "c2"]
    assert by_content[0]["records"] == 2
    assert by_content[0]["metrics"]["plays"] == 30
    assert by_content[1]["records"] == 1
    assert by_content[1]["metrics"]["plays"] == 5


async def test_analytics_tenant_isolation_excludes_other_tenant(client):
    r = await client.get("/api/effects/analytics", params={"tenant_id": "t2"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["records_total"] == 1
    assert body["contents_covered"] == 1
    assert body["metrics_totals"]["plays"] == 999
    assert [row["content_id"] for row in body["by_content"]] == ["c3"]


async def test_analytics_date_window_filters_and_invalid_range_422(client):
    # date_from=09-02：保留 09-02(c2) 与 09-03(c1)，排除 09-01(c1)。
    r = await client.get(
        "/api/effects/analytics",
        params={"tenant_id": "t1", "date_from": "2026-09-02"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["records_total"] == 2
    assert body["metrics_totals"]["plays"] == 25  # 20 + 5

    # date_to=09-02（含当天）：保留 09-01(c1) 与 09-02(c2)，排除 09-03(c1)。
    r = await client.get(
        "/api/effects/analytics",
        params={"tenant_id": "t1", "date_to": "2026-09-02"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["records_total"] == 2
    assert body["metrics_totals"]["plays"] == 15  # 10 + 5

    # from > to：422。
    r = await client.get(
        "/api/effects/analytics",
        params={
            "tenant_id": "t1",
            "date_from": "2026-09-03",
            "date_to": "2026-09-01",
        },
    )
    assert r.status_code == 422


async def test_analytics_requires_tenant_id(client):
    r = await client.get("/api/effects/analytics")
    assert r.status_code == 422
