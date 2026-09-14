"""skill7 通道 WF-01 冷启动识别替换切片集成测试（Q79，M10 WF 替换切片 2/3）。

CAT-RECOG 投递识别整结果单候选（target_type=c1_recognition，intake 锚点）→
pending_review → operations confirmed/modified/rejected →
适配器复用 modeling.submit_recognition，Q1 三分支机械逻辑一字不改；
C7 Layer4 新字段提案通道留挂账（Q79-1）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from app.product.modeling.models import (
    C1IndustryThreshold,
    C1Record,
    C1SignalWeight,
    OpsTodo,
)
from app.product.product_intake import statemachine as sm

OPS = {"id": "ops-1", "roles": ["operations"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}
NOBODY = {"id": "nobody-1", "roles": []}


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
                # Q2 文本三信号 0.50/0.33/0.17（Σ=1）；Q7 general 默认档 0.85。
                C1SignalWeight(signal="name", signal_name="产品名", enabled=True, weight=0.50),
                C1SignalWeight(signal="brief", signal_name="简介", enabled=True, weight=0.33),
                C1SignalWeight(signal="sellpoint", signal_name="卖点", enabled=True, weight=0.17),
                C1IndustryThreshold(
                    industry="general", keywords=[], threshold=0.85,
                    sensitive=False, is_default=True,
                ),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_intake(client, *, status=sm.AI_RECOGNIZING, tenant="t1"):
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": tenant, "profile": {"f_name": "合成面霜", "f_brief": "保湿"}},
    )
    assert r.status_code == 201, r.text
    intake_id = r.json()["intake_id"]
    if status == sm.AI_RECOGNIZING:
        r = await client.post(
            f"/api/intakes/{intake_id}/transitions",
            json={"event": "submit", "actor": CUSTOMER},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == sm.AI_RECOGNIZING
    return intake_id


def _recog(signals=None, **kw):
    payload = {
        "signals": signals or {"name": 0.95, "brief": 0.95, "sellpoint": 0.9},
        "candidates": [
            {"category_id": "synth-c1", "conf": 0.95},
            {"category_id": "synth-c2", "conf": 0.5},
        ],
    }
    payload.update(kw)
    return payload


def _deliver_body(intake_id, *, payload=None, **extra):
    body = {
        "skill_id": "CAT-RECOG",
        "intake_id": intake_id,
        "confidence": 0.9,
        "candidates": [{"target_type": "c1_recognition", "payload": payload or _recog()}],
        "actor": OPS,
    }
    body.update(extra)
    return body


async def _count(session_factory, model) -> int:
    async with session_factory() as session:
        return (await session.scalars(select(func.count()).select_from(model))).one()


# ---------- 投递闸：intake 锚点与 WF 声明对齐（Q79-4） ----------

async def test_deliver_requires_operations_and_intake_anchor(client, session_factory):
    intake_id = await _make_intake(client)
    # 角色闸先于一切。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body("intake-nope", actor=NOBODY)
    )
    assert r.status_code == 403
    # operations 打不存在 intake → 404。
    r = await client.post("/api/skill-runs", json=_deliver_body("intake-nope"))
    assert r.status_code == 404
    # 未注册 Skill → 422。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(intake_id, skill_id="NO-SUCH")
    )
    assert r.status_code == 422
    # 非候选产出步骤（PARSE）带候选投递 → 422。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(intake_id, skill_id="PARSE")
    )
    assert r.status_code == 422
    # target_type 与 WF 声明不一致 → 422。
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(
            intake_id,
            candidates=[{"target_type": "pwc_combo", "payload": {"combos": []}}],
        ),
    )
    assert r.status_code == 422
    # payload 不符 C1RecognitionRequest（signals 缺失）→ 422。
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(intake_id, payload={"candidates": []}),
    )
    assert r.status_code == 422
    # c1_recognition 必须整结果单候选：两条 → 422。
    two = _deliver_body(intake_id)
    two["candidates"].append(two["candidates"][0])
    r = await client.post("/api/skill-runs", json=two)
    assert r.status_code == 422
    # 锚点二选一：两个都给 / 改用 PS 锚点 → 422。
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(intake_id, product_space_id="ps-x"),
    )
    assert r.status_code == 422
    both = _deliver_body(intake_id)
    both["product_space_id"] = "ps-x"
    r = await client.post("/api/skill-runs", json=both)
    assert r.status_code == 422
    # 两个锚点都不给（schema 层）→ 422。
    neither = _deliver_body(intake_id)
    neither.pop("intake_id")
    r = await client.post("/api/skill-runs", json=neither)
    assert r.status_code == 422


async def test_valid_delivery_lands_pending_without_c1_record(client, session_factory):
    intake_id = await _make_intake(client)
    r = await client.post("/api/skill-runs", json=_deliver_body(intake_id))
    assert r.status_code == 200, r.text
    run = r.json()["run"]
    assert run["wf_id"] == "WF-01"
    assert run["intake_id"] == intake_id
    assert run["product_space_id"] is None
    candidate_id = r.json()["candidate_ids"][0]
    cands = await client.get(
        f"/api/skill-candidates?intake_id={intake_id}&state=pending_review"
    )
    assert [c["candidate_id"] for c in cands.json()["candidates"]] == [candidate_id]
    # 候选未裁前不写 C1Record，intake 仍停在 ai_recognizing（AI 只产候选）。
    assert await _count(session_factory, C1Record) == 0
    detail = await client.get(f"/api/intakes/{intake_id}")
    assert detail.json()["status"] == sm.AI_RECOGNIZING


# ---------- confirmed：适配器复用 submit_recognition，三分支机械不变 ----------

async def test_confirm_high_confidence_direct_approve(client, session_factory):
    intake_id = await _make_intake(client)
    r = await client.post("/api/skill-runs", json=_deliver_body(intake_id))
    candidate_id = r.json()["candidate_ids"][0]

    # Q79-3：裁决角色 = operations；product_reviewer 不行。
    forb = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": REVIEWER},
    )
    assert forb.status_code == 403

    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": OPS},
    )
    assert ok.status_code == 200, ok.text
    view = ok.json()
    assert view["state"] == "applied"
    assert len(view["applied_refs"]) == 1
    # Q1 高置信：auto_confirm 直接 submitted，无 OpsTodo。
    detail = await client.get(f"/api/intakes/{intake_id}")
    assert detail.json()["status"] == sm.SUBMITTED
    assert await _count(session_factory, OpsTodo) == 0
    assert await _count(session_factory, C1Record) == 1


async def test_confirm_mid_confidence_creates_ops_todo(client, session_factory):
    intake_id = await _make_intake(client)
    mid = _recog(signals={"name": 0.7, "brief": 0.7, "sellpoint": 0.7})
    r = await client.post("/api/skill-runs", json=_deliver_body(intake_id, payload=mid))
    candidate_id = r.json()["candidate_ids"][0]
    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": OPS},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["state"] == "applied"
    # Q1 中置信：pending_confirm + 72h OpsTodo，准入后无第二道运营确认以外的变化。
    detail = await client.get(f"/api/intakes/{intake_id}")
    assert detail.json()["status"] == sm.PENDING_CONFIRM
    assert await _count(session_factory, OpsTodo) == 1


async def test_low_confidence_without_pending_id_fails_then_modified_succeeds(
    client, session_factory
):
    intake_id = await _make_intake(client)
    low = _recog(signals={"name": 0.4, "brief": 0.4, "sellpoint": 0.4})
    low.pop("candidates")
    r = await client.post("/api/skill-runs", json=_deliver_body(intake_id, payload=low))
    candidate_id = r.json()["candidate_ids"][0]

    # 适配器机械逻辑不变：cold_start 缺 category_pending_id → InvalidDecision 422，
    # 事务回滚，候选留在 pending_review。
    bad = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": OPS},
    )
    assert bad.status_code == 422, bad.text
    cands = await client.get(
        f"/api/skill-candidates?intake_id={intake_id}&state=pending_review"
    )
    assert [c["candidate_id"] for c in cands.json()["candidates"]] == [candidate_id]
    assert await _count(session_factory, C1Record) == 0

    # 改单补上 B2 候选单 → applied + human_modified，intake 转 category_creating。
    fixed = dict(low, category_pending_id="b2-synth-1")
    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "modified", "payload": fixed, "actor": OPS},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["human_modified"] is True
    detail = await client.get(f"/api/intakes/{intake_id}")
    assert detail.json()["status"] == sm.CATEGORY_CREATING
    assert detail.json()["category_pending_id"] == "b2-synth-1"


async def test_reject_archives_without_recognition(client, session_factory):
    intake_id = await _make_intake(client)
    r = await client.post("/api/skill-runs", json=_deliver_body(intake_id))
    candidate_id = r.json()["candidate_ids"][0]
    ok = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "rejected", "reason": "信号不可信，打回重录", "actor": OPS},
    )
    assert ok.status_code == 200
    assert ok.json()["state"] == "archived"
    assert await _count(session_factory, C1Record) == 0
    detail = await client.get(f"/api/intakes/{intake_id}")
    assert detail.json()["status"] == sm.AI_RECOGNIZING


async def test_adapter_wrong_intake_status_409_keeps_candidate_pending(
    client, session_factory
):
    # intake 未提交（stored）：适配器 RecognitionNotAllowed → 409，候选留 pending。
    intake_id = await _make_intake(client, status="stored")
    r = await client.post("/api/skill-runs", json=_deliver_body(intake_id))
    assert r.status_code == 200, r.text
    candidate_id = r.json()["candidate_ids"][0]
    bad = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={"decision": "confirmed", "actor": OPS},
    )
    assert bad.status_code == 409, bad.text
    cands = await client.get(
        f"/api/skill-candidates?intake_id={intake_id}&state=pending_review"
    )
    assert [c["candidate_id"] for c in cands.json()["candidates"]] == [candidate_id]
    assert await _count(session_factory, C1Record) == 0
