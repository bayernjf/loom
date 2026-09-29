"""Q232 MCP HTTP 面集成测试：门控默认关、Agent Key 鉴权、审计留痕。

夹具与 Q88 同型（sqlite 内存库＋`Base.metadata.create_all`）——本面是纯 plan，不碰 PG 专有类型；
真 PG 侧的可解析性由 migration／fullchain 两门覆盖。
"""

from collections.abc import AsyncGenerator
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.actor import Actor
from app.core.api_keys import service
from app.core.api_keys.models import AgentApiKey
from app.core.db import Base, get_session
from app.core.mcp import router as mcp_router
from app.core.models import AuditLog
from app.main import app

PLATFORM_ADMIN = Actor(id="pa-1", roles=["platform_admin"])


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
async def issued(session_factory):
    async with session_factory() as session:
        _row, secret = await service.issue_key(session, "mcp-agent", PLATFORM_ADMIN)
        await session.commit()  # issue_key 只 flush：不提交则钥匙根本不在库里，后续全成 401 假绿
    return secret


@pytest.fixture
def gate_open(monkeypatch):
    """门控开：只替换 router 模块内的 get_settings，不动全局配置。"""
    monkeypatch.setattr(mcp_router, "get_settings", lambda: SimpleNamespace(mcp_enabled=True))


@pytest_asyncio.fixture
async def client(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _rpc(method: str, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


@pytest.mark.asyncio
async def test_gate_off_is_404_even_with_a_valid_key(client, issued) -> None:
    """默认关＝面不存在：404 而非 403，不告诉外部"这里有东西"。"""
    resp = await client.post("/mcp", json=_rpc("tools/list"), headers={"Authorization": f"Bearer {issued}"})
    assert resp.status_code == 404
    assert "disabled" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_valid_key_and_open_gate_lists_the_three_plan_tools(client, issued, gate_open) -> None:
    resp = await client.post("/mcp", json=_rpc("tools/list"), headers={"Authorization": f"Bearer {issued}"})
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["resultType"] == "complete" and result["cacheScope"] == "private"
    assert [t["name"] for t in result["tools"]] == [
        "loom_plan_generate_content",
        "loom_plan_compliance_check",
        "loom_plan_effect_backfill",
    ]


@pytest.mark.asyncio
async def test_missing_or_revoked_key_is_401_before_the_gate(client, session_factory, issued, gate_open) -> None:
    """凭证优先于门控：没钥匙连"存不存在"都问不出来。"""
    assert (await client.post("/mcp", json=_rpc("tools/list"))).status_code == 401
    async with session_factory() as session:
        row, second_secret = await service.issue_key(session, "to-revoke", PLATFORM_ADMIN)
        await service.revoke_key(session, row.key_id, PLATFORM_ADMIN)
        await session.commit()
    resp = await client.post("/mcp", json=_rpc("tools/list"), headers={"Authorization": f"Bearer {second_secret}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_tool_call_returns_plan_and_writes_one_audit_row(client, session_factory, issued, gate_open) -> None:
    body = _rpc("tools/call", {"name": "loom_plan_compliance_check", "arguments": {"tenant_id": "t1", "content_id": "c1"}})
    resp = await client.post("/mcp", json=body, headers={"Authorization": f"Bearer {issued}"})
    assert resp.status_code == 200
    assert resp.json()["result"]["resultType"] == "complete"

    async with session_factory() as session:
        rows = list((await session.scalars(select(AuditLog).where(AuditLog.action == "mcp.request"))).all())
        only_key = (await session.scalars(select(AgentApiKey))).one()
    assert len(rows) == 1
    assert rows[0].tenant_id == "_platform"
    assert rows[0].actor_id == only_key.key_id, "审计必须落在已验真的 key_id 上，不是自报 actor"
    detail = rows[0].detail
    assert detail["tool"] == "loom_plan_compliance_check" and detail["method"] == "tools/call"
    assert detail["result_type"] == "complete" and detail["error_code"] is None


@pytest.mark.asyncio
async def test_input_required_and_unknown_tool_are_still_audited(client, session_factory, issued, gate_open) -> None:
    calls = [
        _rpc("tools/call", {"name": "loom_plan_compliance_check", "arguments": {"tenant_id": "t1"}}),
        _rpc("tools/call", {"name": "loom_fcw_assemble", "arguments": {}}),
    ]
    for payload in calls:
        resp = await client.post("/mcp", json=payload, headers={"Authorization": f"Bearer {issued}"})
        assert resp.status_code == 200

    async with session_factory() as session:
        rows = list((await session.scalars(select(AuditLog).where(AuditLog.action == "mcp.request"))).all())
    assert len(rows) == 2, "input_required 与工具级错误也必须留痕，不然外部刷错误查不到"
    assert {r.detail["result_type"] for r in rows} == {"input_required", "complete"}


def test_mcp_post_is_on_the_published_api_surface() -> None:
    """`app.routes` 把 include 包成 `_IncludedRouter`（实测取不到 path），故用 OpenAPI 这个真可观测面。"""
    paths = app.openapi()["paths"]
    assert "/mcp" in paths, "router 挂了但没发布 ⇒ 外部 404，只测 dispatcher 查不出来"
    assert "post" in paths["/mcp"]


@pytest.mark.asyncio
async def test_discovery_reports_the_spec_version_we_read(client, issued, gate_open) -> None:
    resp = await client.post("/mcp", json=_rpc("server/discover"), headers={"Authorization": f"Bearer {issued}"})
    result = resp.json()["result"]
    assert result["supportedVersions"] == ["2026-07-28"]
    assert result["capabilities"]["tools"]["listChanged"] is False
    assert set(result["capabilities"]) == {"tools"}, "不实现的 prompts/resources 不得声明"
    assert "plan" in result["instructions"]


@pytest.mark.asyncio
async def test_removed_ping_is_a_method_not_found_error(client, issued, gate_open) -> None:
    resp = await client.post("/mcp", json=_rpc("ping"), headers={"Authorization": f"Bearer {issued}"})
    assert resp.status_code == 200
    error = resp.json()["error"]
    assert error["code"] == -32601 and "ping" in error["message"]
