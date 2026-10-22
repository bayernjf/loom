"""M4/T-M4-02 集成测试：内容底座 HTTP API（设计 §4.5）。

- POST /api/v1/content/requests → 201 pending_review；幂等；banned 422
- POST /api/v1/content/{id}/review → confirmed/modified/rejected
- 重复裁决 409、未知候选 404
- GET 列表（过滤）/ 单个
create_all 建 content_candidates（迁移 0065 与表模型同构）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 显式导入确保表注册进 Base.metadata。
from app.core.content_base import models as _models  # noqa: F401
from app.core.db import Base, get_session
from app.main import app

ACTOR = {"id": "owner-1", "roles": ["owner"]}


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
