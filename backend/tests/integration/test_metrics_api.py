"""Q181：/metrics 端点与 HTTP 中间件集成测试。

验证：端点 200 + Prometheus 文本；请求后按「路由模板」（非原始 id 路径）
记录 method/path/status；up gauge 恒 1。
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import Base, get_session
from app.main import app


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_metrics_endpoint_serves_prometheus_text(client) -> None:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "# TYPE http_requests_total counter" in resp.text
    assert "http_request_duration_seconds" in resp.text
    assert "up 1" in resp.text


async def test_middleway_records_route_template_not_raw_id(client) -> None:
    # 命中 GET /api/fcw/{final_id} 模板；final 不存在业务 404，但路由已匹配。
    resp = await client.get("/api/fcw/some-final-id")
    assert resp.status_code == 404
    text = (await client.get("/metrics")).text
    assert 'path="/api/fcw/{final_id}"' in text
    assert 'status="404"' in text
    # 原始 id 不得进入任何 path 标签值。
    path_labels = [
        line for line in text.splitlines() if "path=" in line
    ]
    assert all("some-final-id" not in line for line in path_labels)
