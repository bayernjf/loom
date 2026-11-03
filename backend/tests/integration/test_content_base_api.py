"""M4/T-M4-02 集成测试：内容底座 HTTP API（设计 §4.5）。

- POST /api/v1/content/requests → 201 pending_review；幂等；banned 422
- POST /api/v1/content/{id}/review → confirmed/modified/rejected
- 重复裁决 409、未知候选 404
- GET 列表（过滤）/ 单个
- P0-1（2026-11-02 评审）：四口全部挂 Agent Key——无令牌/错误令牌/吊销令牌统一 401
create_all 建 content_candidates（迁移 0065 与表模型同构）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.actor import Actor
from app.core.api_keys.service import issue_key, revoke_key

# 显式导入确保表注册进 Base.metadata。
from app.core.content_base import models as _models  # noqa: F401
from app.core.db import Base, get_session
from app.core.rbac import PLATFORM_ADMIN
from app.main import app

ACTOR = {"id": "owner-1", "roles": ["owner"]}


@pytest_asyncio.fixture
async def harness():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    async with factory() as session:
        issuer = Actor(id="admin-1", roles=[PLATFORM_ADMIN])
        _row, secret = await issue_key(session, "content-agent", issuer)
        dead_row, dead_secret = await issue_key(session, "content-agent-dead", issuer)
        await revoke_key(session, dead_row.key_id, issuer)
        await session.commit()  # issue_key 只 flush：不提交则钥匙不在库里，全成 401 假绿
    yield {"secret": secret, "dead": dead_secret}
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(harness):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {harness['secret']}"},
    ) as ac:
        yield ac


def _request(**overrides) -> dict:
    body: dict = {
        "product_id": "sku-1",
        "channel": "douyin",
        "content_type": "detail",
        "inputs": {"title": "纯棉T恤"},
        "actor": ACTOR,
    }
    body.update(overrides)
    return body


async def test_submit_returns_pending_review(client) -> None:
    resp = await client.post("/api/v1/content/requests", json=_request())
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending_review"
    assert data["evidence_refs"]
    assert data["final_body"] is None


async def test_idempotent_key_returns_same_candidate(client) -> None:
    first = await client.post("/api/v1/content/requests", json=_request(idempotency_key="k-1"))
    second = await client.post("/api/v1/content/requests", json=_request(idempotency_key="k-1"))
    assert first.json()["candidate_id"] == second.json()["candidate_id"]


async def test_banned_word_returns_422(client) -> None:
    body = _request(
        inputs={"title": "全网最有效"},
        constraints={"banned": ["最有效"]},
    )
    resp = await client.post("/api/v1/content/requests", json=body)
    assert resp.status_code == 422


async def test_submit_with_locale_succeeds(client) -> None:
    # T-M9-02：请求可指定 locale，契约接受新字段且不影响既有产出路径。
    resp = await client.post("/api/v1/content/requests", json=_request(locale="en-US"))
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending_review"
    assert data["evidence_refs"]


async def _submit(client) -> str:
    resp = await client.post("/api/v1/content/requests", json=_request())
    return resp.json()["candidate_id"]


async def test_review_confirmed(client) -> None:
    candidate_id = await _submit(client)
    resp = await client.post(
        f"/api/v1/content/{candidate_id}/review",
        json={"decision": "confirmed", "actor": ACTOR},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["final_body"] == data["body"]


async def test_review_modified_requires_final_body(client) -> None:
    candidate_id = await _submit(client)
    resp = await client.post(
        f"/api/v1/content/{candidate_id}/review",
        json={"decision": "modified", "actor": ACTOR},
    )
    assert resp.status_code == 422


async def test_review_modified_with_body(client) -> None:
    candidate_id = await _submit(client)
    resp = await client.post(
        f"/api/v1/content/{candidate_id}/review",
        json={
            "decision": "modified",
            "final_body": {"text": "人工改写"},
            "actor": ACTOR,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["final_body"] == {"text": "人工改写"}


async def test_review_rejected(client) -> None:
    candidate_id = await _submit(client)
    resp = await client.post(
        f"/api/v1/content/{candidate_id}/review",
        json={"decision": "rejected", "note": "不合规", "actor": ACTOR},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["final_body"] is None


async def test_review_twice_returns_409(client) -> None:
    candidate_id = await _submit(client)
    await client.post(
        f"/api/v1/content/{candidate_id}/review",
        json={"decision": "confirmed", "actor": ACTOR},
    )
    resp = await client.post(
        f"/api/v1/content/{candidate_id}/review",
        json={"decision": "rejected", "actor": ACTOR},
    )
    assert resp.status_code == 409


async def test_review_unknown_candidate_returns_404(client) -> None:
    resp = await client.post(
        "/api/v1/content/nope/review",
        json={"decision": "confirmed", "actor": ACTOR},
    )
    assert resp.status_code == 404


async def test_list_candidates_with_filter(client) -> None:
    await _submit(client)
    resp = await client.get("/api/v1/content", params={"status": "pending_review"})
    assert resp.status_code == 200
    rows = resp.json()["candidates"]
    assert len(rows) == 1
    assert rows[0]["status"] == "pending_review"


async def test_get_single_candidate(client) -> None:
    candidate_id = await _submit(client)
    resp = await client.get(f"/api/v1/content/{candidate_id}")
    assert resp.status_code == 200
    assert resp.json()["candidate_id"] == candidate_id


async def test_get_unknown_returns_404(client) -> None:
    resp = await client.get("/api/v1/content/nope")
    assert resp.status_code == 404


# ---------- P0-1：无鉴权面收口（缺/错/吊销统一 401，不区分原因） ----------


async def test_missing_token_all_four_endpoints_401(client) -> None:
    payload = _request()
    endpoints = [
        ("POST", "/api/v1/content/requests", {"json": payload}),
        ("POST", "/api/v1/content/some-id/review", {"json": {"decision": "confirmed", "actor": ACTOR}}),
        ("GET", "/api/v1/content", {}),
        ("GET", "/api/v1/content/some-id", {}),
    ]
    for method, path, kwargs in endpoints:
        resp = await client.request(method, path, headers={"Authorization": ""}, **kwargs)
        assert resp.status_code == 401, f"{method} {path} 无令牌应 401，实得 {resp.status_code}"


async def test_bad_token_401(client) -> None:
    resp = await client.post(
        "/api/v1/content/requests",
        json=_request(),
        headers={"Authorization": "Bearer loom_nope"},
    )
    assert resp.status_code == 401


async def test_revoked_token_401(client, harness) -> None:
    resp = await client.post(
        "/api/v1/content/requests",
        json=_request(),
        headers={"Authorization": f"Bearer {harness['dead']}"},
    )
    assert resp.status_code == 401


async def test_valid_token_still_works(client) -> None:
    # 合法令牌全流程不回归（防 fail-closed 修成 fail-for-everyone）
    resp = await client.post("/api/v1/content/requests", json=_request())
    assert resp.status_code == 201
    candidate_id = resp.json()["candidate_id"]
    assert (await client.get(f"/api/v1/content/{candidate_id}")).status_code == 200
    assert (await client.get("/api/v1/content")).status_code == 200
