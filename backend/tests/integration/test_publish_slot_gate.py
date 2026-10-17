"""Q368（硬闸 #12 / Q35）：AI 新发布位候选 → 人工评估闭环集成测试。

覆盖：AI 候选创建（四维强制全 0、gate=pending_gate、score_source=ai）、
重复 code 409、extra 传四维 422、审批转正式位（gate→approved、四维写入、
score_source→manual_eval）、审批非 pending 409、列表 gate 过滤、写口角色闸。
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from tests.integration.staff_tokens import acting_as, bearer, issue_write_token

OPS = {"id": "ops-1", "roles": ["operations"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
OPS_QS = "actor_id=ops-1&roles=operations"

AI_SLOT = {
    "platform": "x_platform",
    "code": "X-AI-01",
    "name": "X 平台 AI 识别新位",
    "slot_type": "story",
    "chars_max": 120,
    "source_url": "https://example.com/ai-source",
}


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    app.dependency_overrides[get_auth_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async with session_factory() as session:
        session.add_all([ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


async def _make_ai_candidate(client, code="X-AI-01") -> dict:
    resp = await client.post(
        "/api/admin/publish-slots/ai-candidate",
        json={"item": {**AI_SLOT, "code": code}, "actor": OPS},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_ai_candidate_creates_pending_zero_dims(client):
    body = await _make_ai_candidate(client)
    assert body["gate"] == "pending_gate"
    assert body["score_source"] == "ai"
    assert (body["traffic"], body["safe"], body["conv"], body["load"]) == (0.0,) * 4
    assert body["status"] == "active"
    assert body["code"] == "X-AI-01"


async def test_ai_candidate_rejects_dim_scores(client):
    # 诚实报错：AI 候选契约不含四维（extra=forbid），传分即 422，防 AI 编造主观分。
    resp = await client.post(
        "/api/admin/publish-slots/ai-candidate",
        json={"item": {**AI_SLOT, "traffic": 90}, "actor": OPS},
    )
    assert resp.status_code == 422


async def test_ai_candidate_duplicate_code_conflicts(client):
    await _make_ai_candidate(client)
    resp = await client.post(
        "/api/admin/publish-slots/ai-candidate",
        json={"item": AI_SLOT, "actor": OPS},
    )
    assert resp.status_code == 409


async def test_ai_candidate_requires_operations(client):
    async with acting_as(client, ["product_reviewer"], staff_id="s-rev"):
        resp = await client.post(
            "/api/admin/publish-slots/ai-candidate",
            json={"item": AI_SLOT, "actor": REVIEWER},
        )
    assert resp.status_code == 403


async def test_approve_pending_slot_writes_dims(client):
    body = await _make_ai_candidate(client)
    resp = await client.post(
        f"/api/admin/publish-slots/{body['slot_id']}/approve",
        json={"traffic": 70, "safe": 60, "conv": 45, "load": 90, "actor": OPS},
    )
    assert resp.status_code == 200, resp.text
    approved = resp.json()
    assert approved["gate"] == "approved"
    assert approved["score_source"] == "manual_eval"
    assert (approved["traffic"], approved["safe"], approved["conv"], approved["load"]) == (
        70,
        60,
        45,
        90,
    )


async def test_approve_rejects_out_of_range_dims(client):
    body = await _make_ai_candidate(client)
    resp = await client.post(
        f"/api/admin/publish-slots/{body['slot_id']}/approve",
        json={"traffic": 101, "safe": 60, "conv": 45, "load": 90, "actor": OPS},
    )
    assert resp.status_code == 422


async def test_approve_non_pending_slot_conflicts(client):
    # 人工录入的正式位不可再走审批（gate 恒 approved，非 pending_gate → 409）。
    manual = await client.post(
        "/api/admin/publish-slots",
        json={
            "item": {
                "platform": "x_platform",
                "code": "X-M-01",
                "name": "人工录入位",
                "slot_type": "main",
            },
            "actor": OPS,
        },
    )
    assert manual.status_code == 201, manual.text
    resp = await client.post(
        f"/api/admin/publish-slots/{manual.json()['slot_id']}/approve",
        json={"traffic": 1, "safe": 1, "conv": 1, "load": 1, "actor": OPS},
    )
    assert resp.status_code == 409


async def test_manual_upsert_cannot_carry_gate(client):
    # gate 是状态机字段：人工录入/更新一律 approved，body 传 pending_gate 不生效。
    resp = await client.post(
        "/api/admin/publish-slots",
        json={
            "item": {
                "platform": "x_platform",
                "code": "X-M-02",
                "name": "传 gate 的录入",
                "slot_type": "main",
                "gate": "pending_gate",
            },
            "actor": OPS,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["gate"] == "approved"
    # 更新同样不能改 gate。
    up = await client.put(
        f"/api/admin/publish-slots/{resp.json()['slot_id']}",
        json={
            "item": {
                "platform": "x_platform",
                "code": "X-M-02",
                "name": "改名",
                "slot_type": "main",
                "gate": "pending_gate",
            },
            "actor": OPS,
        },
    )
    assert up.status_code == 200
    assert up.json()["gate"] == "approved"


async def test_list_slots_gate_filter(client):
    await _make_ai_candidate(client, code="X-AI-01")
    await _make_ai_candidate(client, code="X-AI-02")
    await client.post(
        "/api/admin/publish-slots",
        json={
            "item": {
                "platform": "x_platform",
                "code": "X-M-03",
                "name": "正式位",
                "slot_type": "main",
            },
            "actor": OPS,
        },
    )
    pending = await client.get(f"/api/admin/publish-slots?{OPS_QS}&gate=pending_gate")
    assert pending.status_code == 200
    codes = {row["code"] for row in pending.json()}
    assert codes == {"X-AI-01", "X-AI-02"}
    all_rows = await client.get(f"/api/admin/publish-slots?{OPS_QS}")
    assert len(all_rows.json()) == 3
