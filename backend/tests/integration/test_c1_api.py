from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.actor import Actor
from app.core.db import Base, get_session
from app.main import app
from app.product.modeling import service as modeling_service
from app.product.modeling.models import (
    C1IndustryThreshold,
    C1SignalWeight,
)
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import G2Field

OPS = {"id": "ops-1", "roles": ["operations"]}
DICT_ADMIN = {"id": "dict-1", "roles": ["dictionary_admin"]}
PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


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
        session.add_all(
            [
                G2Field(fid="f_name", cat="common", field_name="产品名"),
                G2Field(fid="f_brief", cat="common", field_name="简介"),
                G2Field(fid="g2_extra", cat="selling", field_name="扩展字段"),
                C1SignalWeight(signal="name", signal_name="产品名", enabled=True, weight=0.50),
                C1SignalWeight(signal="brief", signal_name="简介", enabled=True, weight=0.33),
                C1SignalWeight(signal="sellpoint", signal_name="卖点", enabled=True, weight=0.17),
                C1IndustryThreshold(
                    industry="medical", keywords=["医用"], threshold=0.90, sensitive=True
                ),
                C1IndustryThreshold(
                    industry="electronics", keywords=["电子"], threshold=0.80, sensitive=False
                ),
                C1IndustryThreshold(
                    industry="general", keywords=[], threshold=0.85,
                    sensitive=False, is_default=True
                ),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _recognize(client, intake_id, *, signals, candidates=None, industry=None,
                     pending=None, actor=OPS):
    body = {"signals": signals, "actor": actor}
    if candidates is not None:
        body["candidates"] = candidates
    if industry:
        body["industry"] = industry
    if pending:
        body["category_pending_id"] = pending
    return await client.post(f"/api/intakes/{intake_id}/c1-recognition", json=body)


async def _submitted_intake(client) -> str:
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "面霜", "f_brief": "保湿修护"}},
    )
    intake_id = r.json()["intake_id"]
    r = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "submit", "actor": CUSTOMER},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == sm.AI_RECOGNIZING
    return intake_id


async def test_high_confidence_auto_approves(client):
    intake_id = await _submitted_intake(client)
    r = await _recognize(
        client, intake_id,
        signals={"name": 0.95, "brief": 0.95, "sellpoint": 0.9},
        candidates=[{"category_id": "c1", "conf": 0.95}, {"category_id": "c2", "conf": 0.5}],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["branch"] == "direct_approve"
    assert body["industry"] == "general"
    assert body["intake_status"] == sm.SUBMITTED
    assert body["todo_id"] is None


async def test_mid_confidence_creates_ops_todo_and_sweep_escalates(client, session_factory):
    intake_id = await _submitted_intake(client)
    r = await _recognize(
        client, intake_id,
        signals={"name": 0.7, "brief": 0.7, "sellpoint": 0.7},
        candidates=[{"category_id": "c1", "conf": 0.72}, {"category_id": "c2", "conf": 0.5}],
    )
    assert r.json()["branch"] == "ops_assist"
    assert r.json()["intake_status"] == sm.PENDING_CONFIRM
    todo_id = r.json()["todo_id"]
    assert todo_id

    # 未到 72h 不升级。
    async with session_factory() as session:
        assert await modeling_service.escalate_due_todos(session, Actor(**PLATFORM_ADMIN)) == 0

    # 超过 72h sweep 升级（Q4）。
    future = datetime.now(UTC) + timedelta(hours=73)
    async with session_factory() as session:
        assert (
            await modeling_service.escalate_due_todos(
                session, Actor(**PLATFORM_ADMIN), now=future
            )
            == 1
        )

    # 候选外类目 422；选候选内类目 → 已提交，待办 resolved。
    r = await client.post(
        f"/api/intakes/{intake_id}/ops-decision",
        json={"decision": "select", "category_id": "nope", "actor": OPS},
    )
    assert r.status_code == 422
    r = await client.post(
        f"/api/intakes/{intake_id}/ops-decision",
        json={"decision": "select", "category_id": "c1", "actor": OPS},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"
    r = await client.get(f"/api/intakes/{intake_id}")
    assert r.json()["status"] == sm.SUBMITTED


async def test_reject_all_routes_to_cold_start(client):
    intake_id = await _submitted_intake(client)
    await _recognize(
        client, intake_id,
        signals={"name": 0.65, "brief": 0.65, "sellpoint": 0.65},
    )
    # 全否必须带 B2 候选单。
    r = await client.post(
        f"/api/intakes/{intake_id}/ops-decision",
        json={"decision": "reject_all", "actor": OPS},
    )
    assert r.status_code == 422
    r = await client.post(
        f"/api/intakes/{intake_id}/ops-decision",
        json={"decision": "reject_all", "category_pending_id": "b2-9", "actor": OPS},
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/intakes/{intake_id}")
    assert r.json()["status"] == sm.CATEGORY_CREATING
    assert r.json()["category_pending_id"] == "b2-9"


async def test_low_confidence_requires_pending_id_and_enters_category_creating(client):
    intake_id = await _submitted_intake(client)
    r = await _recognize(
        client, intake_id,
        signals={"name": 0.4, "brief": 0.4, "sellpoint": 0.4},
    )
    assert r.status_code == 422
    r = await _recognize(
        client, intake_id,
        signals={"name": 0.4, "brief": 0.4, "sellpoint": 0.4},
        pending="b2-1",
    )
    assert r.status_code == 200
    assert r.json()["branch"] == "cold_start"
    assert r.json()["intake_status"] == sm.CATEGORY_CREATING


async def test_industry_crud_protect_default_and_weight_sum_guard(client):
    r = await client.request(
        "DELETE", "/api/admin/c1/industries/general", json={"actor": OPS}
    )
    assert r.status_code == 409  # 默认档不可删（Q7）

    r = await client.patch(
        "/api/admin/c1/industries/medical",
        json={"threshold": 0.92, "actor": OPS},
    )
    assert r.status_code == 200 and r.json()["threshold"] == 0.92

    r = await client.put(
        "/api/admin/c1/signal-weights",
        json={
            "rows": [
                {"signal": "name", "signal_name": "产品名", "enabled": True, "weight": 0.9},
                {"signal": "brief", "signal_name": "简介", "enabled": True, "weight": 0.2},
            ],
            "actor": OPS,
        },
    )
    assert r.status_code == 422  # Σ 必须精确等于 1（Q2）


async def test_c7_layers_and_fid_guard(client):
    # 父类目 + 一个带 approved 模板的兄长子类目（Layer1/Layer2 准备）。
    r = await client.post("/api/categories", json={"name": "护肤", "actor": DICT_ADMIN})
    parent = r.json()["category_id"]
    r = await client.post(
        "/api/categories",
        json={"name": "面霜", "parent_id": parent, "actor": DICT_ADMIN},
    )
    sibling = r.json()["category_id"]
    r = await client.put(
        f"/api/categories/{sibling}/template",
        json={"field_list": ["f_name", "f_brief"], "status": "approved", "actor": DICT_ADMIN},
    )
    assert r.status_code == 200, r.text

    intake_id = await _submitted_intake(client)

    # Layer1：兄长子类目直接命中 approved 模板。
    r = await client.post(
        f"/api/intakes/{intake_id}/c7-runs",
        json={"category_id": sibling, "required_fids": ["f_name"], "actor": OPS},
    )
    assert r.status_code == 200 and r.json()["layer"] == 1

    # Layer2：同父新类目无模板，继承 product_count 最大的兄弟模板。
    r = await client.post(
        "/api/categories",
        json={"name": "乳液", "parent_id": parent, "actor": DICT_ADMIN},
    )
    new_cat = r.json()["category_id"]
    r = await client.post(
        f"/api/intakes/{intake_id}/c7-runs",
        json={"category_id": new_cat, "required_fids": ["f_name"], "actor": OPS},
    )
    assert r.status_code == 200 and r.json()["layer"] == 2

    # Layer3：独立类目（无兄弟模板），G2 覆盖率 ≥60% 直接挑 G2 字段。
    r = await client.post(
        "/api/categories", json={"name": "独立类目", "actor": DICT_ADMIN}
    )
    solo = r.json()["category_id"]
    r = await client.post(
        f"/api/intakes/{intake_id}/c7-runs",
        json={
            "category_id": solo,
            "required_fids": ["f_name", "f_brief", "g2_extra"],
            "actor": OPS,
        },
    )
    assert r.status_code == 200
    assert r.json()["layer"] == 3

    # Layer4：覆盖率 <60%，新字段进候选；fid:'-' 被 Q68 拦截。
    r = await client.post(
        f"/api/intakes/{intake_id}/c7-runs",
        json={
            "category_id": solo,
            "required_fids": ["f_name", "f_brief", "g2_extra", "missing1", "missing2", "missing3"],
            "l4_proposals": [{"field_name": "新字段A", "definition": "Layer4 生成"}],
            "actor": OPS,
        },
    )
    assert r.status_code == 200
    assert r.json()["layer"] == 4
    assert len(r.json()["candidate_ids"]) == 1

    r = await client.post(
        f"/api/intakes/{intake_id}/c7-runs",
        json={
            "category_id": solo,
            "required_fids": ["f_name"],
            "l4_proposals": [{"field_name": "黑户", "fid": "-"}],
            "actor": OPS,
        },
    )
    assert r.status_code == 422

    # 模板写入同样禁止 fid:'-' 与不存在的 fid（Q68）。
    r = await client.put(
        f"/api/categories/{new_cat}/template",
        json={"field_list": ["-"], "status": "draft", "actor": DICT_ADMIN},
    )
    assert r.status_code == 422
    r = await client.put(
        f"/api/categories/{new_cat}/template",
        json={"field_list": ["f_name", "ghost_fid"], "status": "draft", "actor": DICT_ADMIN},
    )
    assert r.status_code == 422
