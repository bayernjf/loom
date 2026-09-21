"""Q150 集成测试：A2A 封臣端点（Zeus 联邦 plan 模式第一阶段）。

口径（02 C1.94 / docs/design-a2a-vassal.md，四项裁决均按草案）：
- Agent Card 三发现路径公开（无 Key），fealty + 三件 plan skills；
- POST /api/a2a/tasks 复用 Q88 Agent Key Bearer 验签（无/错/吊销 Key 401）；
- plan 模式不触链、不花 token、不越 Gate，任务落 a2a.task 审计（tenant=_platform）；
- JSON-RPC：tasks/send 同步、tasks/sendSubscribe SSE、tasks/get、tasks/cancel。
create_all 不跑迁移（本切片零迁移）。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.a2a import rpc
from app.core.actor import Actor
from app.core.api_keys import service
from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.main import app

PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}


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
    rpc.reset_for_tests()
    yield factory
    rpc.reset_for_tests()
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _issue(session_factory, name="zeus-key"):
    async with session_factory() as session:
        row, secret = await service.issue_key(session, name, Actor(**PLATFORM_ADMIN))
        await session.commit()
        return row.key_id, secret


def _send_payload(skill: str, params: dict, run_id: str | None = None, method: str = "tasks/send") -> dict:
    data = {"skill": skill, **params}
    message: dict = {"role": "user", "parts": [{"kind": "data", "data": data}]}
    if run_id:
        message["metadata"] = {"x-zeus-runId": run_id}
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": {"message": message}}


# ---------- Agent Card 发现（公开） ----------

@pytest.mark.parametrize(
    "path",
    [
        "/api/a2a/agent-card",
        "/.well-known/agent-card.json",
        "/.well-known/agent.json",
    ],
)
async def test_agent_card_public_three_paths(client, path):
    resp = await client.get(path)
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "loom"
    assert card["preferredTransport"] == "JSONRPC"
    assert [s["id"] for s in card["skills"]] == [
        "generate-content",
        "compliance-check",
        "effect-backfill",
    ]
    fealty = card["x-zeus-fealty"]
    assert fealty["swornTo"] == "zeus"
    assert fealty["dataPolicy"] == "read-task-scope"
    assert card["authentication"]["schemes"] == ["bearer"]


# ---------- 任务端点鉴权 ----------

async def test_tasks_requires_key_missing_and_bad(client):
    payload = _send_payload("generate-content", {"tenant_id": "t1", "product_id": "p1"})
    no_header = await client.post("/api/a2a/tasks", json=payload)
    assert no_header.status_code == 401
    bad = await client.post(
        "/api/a2a/tasks", json=payload, headers={"Authorization": "Bearer loom_nope"}
    )
    assert bad.status_code == 401


async def test_tasks_revoked_key_401(client, session_factory):
    key_id, secret = await _issue(session_factory)
    async with session_factory() as session:
        await service.revoke_key(session, key_id, Actor(**PLATFORM_ADMIN))
        await session.commit()
    resp = await client.post(
        "/api/a2a/tasks",
        json=_send_payload("generate-content", {"tenant_id": "t1", "product_id": "p1"}),
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 401


# ---------- tasks/send 同步任务 + 审计 ----------

async def test_send_completes_plan_task_and_audits(client, session_factory):
    _, secret = await _issue(session_factory)
    resp = await client.post(
        "/api/a2a/tasks",
        json=_send_payload(
            "generate-content", {"tenant_id": "t1", "product_id": "p1"}, run_id="zeus-run-1"
        ),
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["jsonrpc"] == "2.0" and body["id"] == 1
    task = body["result"]
    assert task["kind"] == "task"
    assert task["status"]["state"] == "completed"
    artifact = task["artifacts"][0]
    report = artifact["x-zeus-report"]
    assert report["cost"]["llmTokens"] == 0
    data_part = artifact["parts"][0]["data"]
    assert data_part["mode"] == "plan" and data_part["skill"] == "generate-content"

    async with session_factory() as session:
        rows = (await session.scalars(
            select(AuditLog).where(AuditLog.action == "a2a.task")
        )).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.tenant_id == "_platform"
        assert row.entity_type == "a2a_task" and row.entity_id == task["id"]
        assert row.detail["skill"] == "generate-content"
        assert row.detail["state"] == "completed"
        assert row.detail["run_id"] == "zeus-run-1"
        assert row.detail["agent_key"] == "zeus-key"


async def test_send_input_required_still_audits_inbound_call(client, session_factory):
    # 入站 Key 调用一律留痕（即使参数不全停在 input-required），skill 缺省为 None。
    _, secret = await _issue(session_factory)
    resp = await client.post(
        "/api/a2a/tasks",
        json=_send_payload("generate-content", {}),
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    task = resp.json()["result"]
    assert task["status"]["state"] == "input-required"
    async with session_factory() as session:
        rows = (await session.scalars(
            select(AuditLog).where(AuditLog.action == "a2a.task")
        )).all()
        assert len(rows) == 1
        assert rows[0].detail["state"] == "input-required"
        assert rows[0].detail["skill"] is None


async def test_send_invalid_jsonrpc_params(client, session_factory):
    _, secret = await _issue(session_factory)
    resp = await client.post(
        "/api/a2a/tasks",
        json={"jsonrpc": "2.0", "id": 9, "method": "tasks/send", "params": {"message": {"role": "agent", "parts": []}}},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32602


# ---------- tasks/get、tasks/cancel ----------

async def test_get_and_cancel_lifecycle(client, session_factory):
    _, secret = await _issue(session_factory)
    headers = {"Authorization": f"Bearer {secret}"}
    # 缺参数 → input-required（非终态，可取消）
    created = await client.post(
        "/api/a2a/tasks", json=_send_payload("generate-content", {}), headers=headers
    )
    task_id = created.json()["result"]["id"]

    got = await client.post(
        "/api/a2a/tasks",
        json={"jsonrpc": "2.0", "id": 2, "method": "tasks/get", "params": {"id": task_id}},
        headers=headers,
    )
    assert got.json()["result"]["id"] == task_id

    canceled = await client.post(
        "/api/a2a/tasks",
        json={"jsonrpc": "2.0", "id": 3, "method": "tasks/cancel", "params": {"id": task_id}},
        headers=headers,
    )
    assert canceled.json()["result"]["status"]["state"] == "canceled"

    again = await client.post(
        "/api/a2a/tasks",
        json={"jsonrpc": "2.0", "id": 4, "method": "tasks/cancel", "params": {"id": task_id}},
        headers=headers,
    )
    assert again.json()["error"]["code"] == -32002

    missing = await client.post(
        "/api/a2a/tasks",
        json={"jsonrpc": "2.0", "id": 5, "method": "tasks/get", "params": {"id": "nope"}},
        headers=headers,
    )
    assert missing.json()["error"]["code"] == -32001

    bogus = await client.post(
        "/api/a2a/tasks",
        json={"jsonrpc": "2.0", "id": 6, "method": "bogus"},
        headers=headers,
    )
    assert bogus.json()["error"]["code"] == -32601


# ---------- tasks/sendSubscribe（SSE） ----------

async def test_send_subscribe_streams_events_then_response(client, session_factory):
    _, secret = await _issue(session_factory)
    async with client.stream(
        "POST",
        "/api/a2a/tasks",
        json=_send_payload(
            "effect-backfill", {"tenant_id": "t1", "content_id": "c1"}, run_id="zeus-run-2"
        , method="tasks/sendSubscribe"),
        headers={"Authorization": f"Bearer {secret}"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        chunks = []
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                chunks.append(line)
    # 至少 submitted/working/artifact/completed 事件 + 最终 JSON-RPC 响应
    assert len(chunks) >= 4
    final = chunks[-1]
    assert '"jsonrpc": "2.0"' in final
    assert '"state": "completed"' in final or '"state":"completed"' in final
