"""skill7 通道 C7 Layer4 新字段提案切片集成测试（Q81，Q79-1 挂账销账）。

TYPE-MATCH 投递整 C7 解析请求单候选（target_type=c7_layer4，intake 锚点）→
pending_review → operations confirmed/modified/rejected →
适配器复用 modeling.resolve_c7：L1→L4 机械判定（Q6/Q68）一项不绕，
实际落在 L1/2/3 时 l4_proposals 不生效；新字段候选后续 Q13 dictionary_admin 转正不变。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from app.product.modeling.models import C7Run, G2FieldCandidate
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import G2Field

OPS = {"id": "ops-1", "roles": ["operations"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
DICT_ADMIN = {"id": "dict-1", "roles": ["dictionary_admin"]}
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
                G2Field(fid="f_name", cat="common", field_name="产品名"),
                G2Field(fid="f_brief", cat="common", field_name="简介"),
                G2Field(fid="g2_extra", cat="selling", field_name="扩展字段"),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_intake(client, *, tenant="t1"):
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": tenant, "profile": {"f_name": "合成面霜", "f_brief": "保湿"}},
    )
    assert r.status_code == 201, r.text
    intake_id = r.json()["intake_id"]
    r = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "submit", "actor": CUSTOMER},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == sm.AI_RECOGNIZING
    return intake_id


async def _make_category(client, *, name, parent_id=None):
    r = await client.post(
        "/api/categories", json={"name": name, "parent_id": parent_id, "actor": DICT_ADMIN}
    )
    assert r.status_code == 201, r.text
    return r.json()["category_id"]


def _c7_payload(category_id, **kw):
    payload = {
        "category_id": category_id,
        # 1/6 G2 覆盖 < 0.6 → Layer4（Q6）。
        "required_fids": ["f_name", "m1", "m2", "m3", "m4", "m5"],
        "l4_proposals": [
            {"field_name": "合成新字段X", "definition": "TYPE-MATCH LLM 新生成"}
        ],
    }
    payload.update(kw)
    return payload


def _deliver_body(intake_id, *, payload=None, category_id="cat-synth", **extra):
    body = {
        "skill_id": "TYPE-MATCH",
        "intake_id": intake_id,
        "confidence": 0.8,
        "candidates": [
            {"target_type": "c7_layer4", "payload": payload or _c7_payload(category_id)}
        ],
        "actor": OPS,
    }
    body.update(extra)
    return body


async def _count(session_factory, model) -> int:
    async with session_factory() as session:
        return (await session.scalars(select(func.count()).select_from(model))).one()


async def _decide(client, candidate_id, body):
    return await client.post(
        f"/api/skill-candidates/{candidate_id}/decision", json=body
    )


# ---------- 投递闸：intake 锚点与 WF 声明对齐（Q79-4/Q81） ----------

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
    # 非候选产出步骤（MISSING-INFO）带候选投递 → 422。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(intake_id, skill_id="MISSING-INFO")
    )
    assert r.status_code == 422
    # target_type 与 WF 声明不一致 → 422。
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(
            intake_id,
            candidates=[{"target_type": "c1_recognition", "payload": {"signals": {}}}],
        ),
    )
    assert r.status_code == 422
    # payload 不符 C7ResolveRequest（category_id 缺失）→ 422。
    r = await client.post(
        "/api/skill-runs",
        json=_deliver_body(intake_id, payload={"required_fids": ["f_name"]}),
    )
    assert r.status_code == 422
    # c7_layer4 必须整 C7 解析单候选：两条 → 422。
    two = _deliver_body(intake_id)
    two["candidates"].append(two["candidates"][0])
    r = await client.post("/api/skill-runs", json=two)
    assert r.status_code == 422
    # 锚点必须是 intake：改用 PS 锚点 / 两个都给 → 422。
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(intake_id, product_space_id="ps-x")
    )
    assert r.status_code == 422
    both = _deliver_body(intake_id)
    both["product_space_id"] = "ps-x"
    r = await client.post("/api/skill-runs", json=both)
    assert r.status_code == 422


async def test_valid_delivery_lands_pending_without_c7_run(
    client, session_factory
):
    intake_id = await _make_intake(client)
    r = await client.post("/api/skill-runs", json=_deliver_body(intake_id))
    assert r.status_code == 200, r.text
    run = r.json()["run"]
    assert run["wf_id"] == "WF-01"
    assert run["skill_id"] == "TYPE-MATCH"
    assert run["intake_id"] == intake_id
    assert run["product_space_id"] is None
    candidate_id = r.json()["candidate_ids"][0]
    cands = await client.get(
        f"/api/skill-candidates?intake_id={intake_id}&state=pending_review"
    )
    assert [c["candidate_id"] for c in cands.json()["candidates"]] == [candidate_id]
    # 候选未裁前不跑 C7、不建 G2 候选（AI 只产候选）。
    assert await _count(session_factory, C7Run) == 0
    assert await _count(session_factory, G2FieldCandidate) == 0


# ---------- confirmed：适配器复用 resolve_c7，L1→L4 机械判定不变 ----------

async def test_confirm_layer4_applies_via_resolve_c7(client, session_factory):
    intake_id = await _make_intake(client)
    solo = await _make_category(client, name="独立类目")
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(intake_id, category_id=solo)
    )
    candidate_id = r.json()["candidate_ids"][0]

    # Q81-3：裁决角色 = operations；product_reviewer 不行。
    forb = await _decide(client, candidate_id, {"decision": "confirmed", "actor": REVIEWER})
    assert forb.status_code == 403

    ok = await _decide(client, candidate_id, {"decision": "confirmed", "actor": OPS})
    assert ok.status_code == 200, ok.text
    view = ok.json()
    assert view["state"] == "applied"
    assert len(view["applied_refs"]) == 1  # c7_run_id

    async with session_factory() as session:
        run = await session.get(C7Run, view["applied_refs"][0])
        assert run.layer == 4
        rows = list((await session.scalars(select(G2FieldCandidate))).all())
    assert len(rows) == 1
    assert rows[0].field_name == "合成新字段X"
    assert rows[0].source_layer == "c7_layer4"
    assert rows[0].status == "pending_gate"  # Q13 转正 Gate 不在本切片


async def test_confirm_landing_layer1_ignores_proposals(client, session_factory):
    # 实际命中 Layer1 时 l4_proposals 自然不生效（整 C7 解析适配器语义）。
    intake_id = await _make_intake(client)
    cat = await _make_category(client, name="模板类目")
    r = await client.put(
        f"/api/categories/{cat}/template",
        json={
            "field_list": ["f_name", "f_brief"],
            "status": "approved",
            "actor": DICT_ADMIN,
        },
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(intake_id, category_id=cat)
    )
    candidate_id = r.json()["candidate_ids"][0]
    ok = await _decide(client, candidate_id, {"decision": "confirmed", "actor": OPS})
    assert ok.status_code == 200, ok.text
    assert await _count(session_factory, C7Run) == 1
    assert await _count(session_factory, G2FieldCandidate) == 0


async def test_reject_archives_without_c7_run(client, session_factory):
    intake_id = await _make_intake(client)
    r = await client.post("/api/skill-runs", json=_deliver_body(intake_id))
    candidate_id = r.json()["candidate_ids"][0]
    ok = await _decide(
        client,
        candidate_id,
        {"decision": "rejected", "reason": "提案不可信", "actor": OPS},
    )
    assert ok.status_code == 200
    assert ok.json()["state"] == "archived"
    assert await _count(session_factory, C7Run) == 0
    assert await _count(session_factory, G2FieldCandidate) == 0


async def test_modified_illegal_fid_422_then_replacement_succeeds(
    client, session_factory
):
    intake_id = await _make_intake(client)
    solo = await _make_category(client, name="独立类目2")
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(intake_id, category_id=solo)
    )
    candidate_id = r.json()["candidate_ids"][0]

    # Q68：l4_proposals 带 fid:'-' 在适配器内被拦（422），事务回滚候选留 pending。
    bad_payload = _c7_payload(
        solo, l4_proposals=[{"field_name": "黑户", "fid": "-"}]
    )
    bad = await _decide(
        client,
        candidate_id,
        {"decision": "modified", "payload": bad_payload, "actor": OPS},
    )
    assert bad.status_code == 422, bad.text
    cands = await client.get(
        f"/api/skill-candidates?intake_id={intake_id}&state=pending_review"
    )
    assert [c["candidate_id"] for c in cands.json()["candidates"]] == [candidate_id]
    assert await _count(session_factory, C7Run) == 0

    # 改单换成合法提案 → applied + human_modified，layer=4。
    fixed = _c7_payload(
        solo, l4_proposals=[{"field_name": "合成改后字段", "definition": "人工改过"}]
    )
    ok = await _decide(
        client,
        candidate_id,
        {"decision": "modified", "payload": fixed, "actor": OPS},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["human_modified"] is True
    async with session_factory() as session:
        run = await session.get(C7Run, ok.json()["applied_refs"][0])
        assert run.layer == 4
        names = list(
            await session.scalars(
                select(G2FieldCandidate.field_name).where(
                    G2FieldCandidate.source_layer == "c7_layer4"
                )
            )
        )
    assert names == ["合成改后字段"]


async def test_category_not_found_confirm_404_keeps_pending(client, session_factory):
    intake_id = await _make_intake(client)
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(intake_id, category_id="cat-nope")
    )
    candidate_id = r.json()["candidate_ids"][0]
    bad = await _decide(client, candidate_id, {"decision": "confirmed", "actor": OPS})
    assert bad.status_code == 404, bad.text
    cands = await client.get(
        f"/api/skill-candidates?intake_id={intake_id}&state=pending_review"
    )
    assert [c["candidate_id"] for c in cands.json()["candidates"]] == [candidate_id]
    assert await _count(session_factory, C7Run) == 0


async def test_same_name_proposal_reuses_global_candidate(
    client, session_factory
):
    # G2 候选是全局字典资产：同名 c7_layer4 提案复用（与 wf02_dim_source 同口径）。
    solo_a = await _make_category(client, name="独立类目A")
    intake_a = await _make_intake(client, tenant="t1")
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(intake_a, category_id=solo_a)
    )
    ok = await _decide(
        client, r.json()["candidate_ids"][0],
        {"decision": "confirmed", "actor": OPS},
    )
    assert ok.status_code == 200, ok.text
    assert await _count(session_factory, G2FieldCandidate) == 1

    # 另一申请单（同租户）提同名字段 → 复用同一 candidate_id，不重复建。
    solo_b = await _make_category(client, name="独立类目B")
    intake_b = await _make_intake(client, tenant="t1")
    r = await client.post(
        "/api/skill-runs", json=_deliver_body(intake_b, category_id=solo_b)
    )
    ok = await _decide(
        client, r.json()["candidate_ids"][0],
        {"decision": "confirmed", "actor": OPS},
    )
    assert ok.status_code == 200, ok.text
    assert await _count(session_factory, G2FieldCandidate) == 1
    assert await _count(session_factory, C7Run) == 2
