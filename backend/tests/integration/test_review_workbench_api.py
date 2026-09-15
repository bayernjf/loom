"""统一审核工作台集成测试（Q93，Q70 一期）：跨型队列 + 置信度批量通过。

队列断言用直插 SkillRun/SkillCandidate/C1IndustryThreshold（GET 只读）；
批量通过 happy path 走真实投递 + atom_batch 适配器（前置已批准字段池），
预检失败（角色混批/高风险/低置信/非 pending/不存在）要求不留任何写入。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.skill7.models import SkillCandidate, SkillRun
from app.main import app
from app.product.fieldpool.models import FPSourceRoute
from app.product.modeling.models import C1IndustryThreshold
from app.product.product_intake.models import (
    ProductIntakeApplication,
    ProductSpace,
)

NOW = datetime.now(UTC)

OPS = {"id": "ops-1", "roles": ["operations"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
NOBODY = {"id": "nobody-1", "roles": ["dictionary_admin"]}


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
            FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
            FPSourceRoute(route="compliance_risk", name="合规风险面", sort_order=2),
            C1IndustryThreshold(
                industry="medical",
                keywords=[],
                threshold=0.85,
                sensitive=True,
                is_default=False,
            ),
            C1IndustryThreshold(
                industry="general",
                keywords=[],
                threshold=0.85,
                sensitive=False,
                is_default=True,
            ),
        ])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------- 直插构造（只读队列用） ----------


def _run(run_id: str, *, confidence: float | None, at: datetime) -> SkillRun:
    return SkillRun(
        run_id=run_id,
        skill_id="SK",
        wf_id="WF-04",
        status="succeeded",
        source="delivery",
        confidence=confidence,
        created_at=at,
    )


def _candidate(
    candidate_id: str,
    *,
    run_id: str,
    wf_id: str,
    target_type: str,
    payload: dict,
    state: str = "pending_review",
    at: datetime,
    candidate_index: int = 0,
) -> SkillCandidate:
    return SkillCandidate(
        candidate_id=candidate_id,
        run_id=run_id,
        candidate_index=candidate_index,
        skill_id="SK",
        wf_id=wf_id,
        tenant_id="t1",
        target_type=target_type,
        payload=payload,
        state=state,
        created_at=at,
    )


async def _seed_queue(session_factory):
    async with session_factory() as session:
        session.add_all([
            _run("r-crit", confidence=0.99, at=NOW - timedelta(hours=3)),
            _run("r-high", confidence=0.95, at=NOW - timedelta(hours=1)),
            _run("r-atom-low", confidence=0.95, at=NOW - timedelta(hours=2)),
            _run("r-c1-low", confidence=0.9, at=NOW - timedelta(hours=4)),
            _run("r-pwc-lowconf", confidence=0.5, at=NOW - timedelta(hours=5)),
            _run("r-none", confidence=None, at=NOW - timedelta(hours=6)),
            _candidate(
                "c-crit",
                run_id="r-crit",
                wf_id="WF-01",
                target_type="c1_recognition",
                payload={"signals": {}, "industry": "medical"},
                at=NOW - timedelta(hours=3),
            ),
            _candidate(
                "c-high",
                run_id="r-high",
                wf_id="WF-03",
                target_type="atom_batch",
                payload={
                    "items": [
                        {"content": "a", "dimension_id": "d1", "ai_risk": "low"},
                        {"content": "b", "dimension_id": "d2", "ai_risk": "high"},
                    ]
                },
                at=NOW - timedelta(hours=1),
            ),
            _candidate(
                "c-atom-low",
                run_id="r-atom-low",
                wf_id="WF-03",
                target_type="atom_batch",
                payload={
                    "items": [
                        {"content": "c", "dimension_id": "d1", "ai_risk": "low"},
                    ]
                },
                at=NOW - timedelta(hours=2),
            ),
            _candidate(
                "c-c1-low",
                run_id="r-c1-low",
                wf_id="WF-01",
                target_type="c1_recognition",
                payload={"signals": {}, "industry": "general"},
                at=NOW - timedelta(hours=4),
            ),
            _candidate(
                "c-pwc",
                run_id="r-pwc-lowconf",
                wf_id="WF-04",
                target_type="pwc_combo",
                payload={"combos": [{"atom_ids": ["a1", "a2"]}]},
                at=NOW - timedelta(hours=5),
            ),
            _candidate(
                "c-none",
                run_id="r-none",
                wf_id="WF-04",
                target_type="pwc_combo",
                payload={"combos": [{"atom_ids": ["a3", "a4"]}]},
                at=NOW - timedelta(hours=6),
            ),
            _candidate(
                "c-applied",
                run_id="r-atom-low",
                candidate_index=1,
                wf_id="WF-03",
                target_type="atom_batch",
                payload={"items": []},
                state="applied",
                at=NOW - timedelta(days=2),
            ),
        ])
        await session.commit()


def _params(actor: dict, **extra) -> list[tuple[str, str]]:
    out = [("actor_id", actor["id"])]
    out.extend(("roles", role) for role in actor["roles"])
    out.extend((k, str(v)) for k, v in extra.items())
    return out


# ---------- RBAC ----------


async def test_queue_requires_actor_and_any_wf_gate_role(client, session_factory):
    await _seed_queue(session_factory)

    resp = await client.get("/api/review-workbench/candidates")
    assert resp.status_code == 422

    resp = await client.get(
        "/api/review-workbench/candidates", params=_params(NOBODY)
    )
    assert resp.status_code == 403

    # platform_admin 不是裁决角色，不放行（接缝③）。
    resp = await client.get(
        "/api/review-workbench/candidates", params=_params(ADMIN)
    )
    assert resp.status_code == 403

    for actor in (OPS, REVIEWER):
        resp = await client.get(
            "/api/review-workbench/candidates", params=_params(actor)
        )
        assert resp.status_code == 200, resp.text


# ---------- 风险归一 / 排序 / 筛选 / 分页 ----------


async def test_queue_orders_by_risk_then_creation_and_flags_eligibility(
    client, session_factory
):
    await _seed_queue(session_factory)
    resp = await client.get(
        "/api/review-workbench/candidates", params=_params(REVIEWER, limit=200)
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()

    assert report["total"] == 6
    assert report["batch_pass_confidence"] == 0.85
    ids = [row["candidate_id"] for row in report["candidates"]]
    # 风险降档；同档内创建时间最老优先（等待最久先审）。
    assert ids == [
        "c-crit",
        "c-high",
        "c-none",
        "c-pwc",
        "c-c1-low",
        "c-atom-low",
    ]

    by_id = {row["candidate_id"]: row for row in report["candidates"]}
    crit = by_id["c-crit"]
    assert crit["risk_level"] == "critical"
    assert crit["risk_rank"] == 3
    assert crit["risk_reason"] == "c1_recognition.sensitive_industry"
    assert crit["batch_eligible"] is False
    assert crit["wait_seconds"] is not None and crit["wait_seconds"] >= 3 * 3600 - 60

    high = by_id["c-high"]
    assert high["risk_level"] == "high"
    assert high["risk_reason"] == "atom_batch.max_ai_risk"
    assert high["batch_eligible"] is False

    assert by_id["c-atom-low"]["risk_level"] == "low"
    assert by_id["c-atom-low"]["batch_eligible"] is True
    assert by_id["c-c1-low"]["risk_level"] == "low"
    assert by_id["c-c1-low"]["batch_eligible"] is True
    assert by_id["c-pwc"]["batch_eligible"] is False  # confidence 0.5 <= 0.85
    assert by_id["c-none"]["batch_eligible"] is False  # confidence missing


async def test_queue_filters_and_paginates(client, session_factory):
    await _seed_queue(session_factory)
    base = "/api/review-workbench/candidates"

    resp = await client.get(
        base, params=_params(REVIEWER, risk_level="critical")
    )
    assert [r["candidate_id"] for r in resp.json()["candidates"]] == ["c-crit"]

    resp = await client.get(
        base,
        params=_params(REVIEWER) + [("target_type", "atom_batch")],
    )
    assert [r["candidate_id"] for r in resp.json()["candidates"]] == [
        "c-high",
        "c-atom-low",
    ]

    resp = await client.get(base, params=_params(OPS, wf_id="WF-01"))
    assert [r["candidate_id"] for r in resp.json()["candidates"]] == [
        "c-crit",
        "c-c1-low",
    ]

    resp = await client.get(
        base, params=_params(REVIEWER, state="applied")
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["candidates"][0]["candidate_id"] == "c-applied"
    assert body["candidates"][0]["batch_eligible"] is False
    assert body["candidates"][0]["wait_seconds"] is None

    resp = await client.get(
        base, params=_params(REVIEWER, limit=2, offset=2)
    )
    body = resp.json()
    assert body["total"] == 6
    assert [r["candidate_id"] for r in body["candidates"]] == [
        "c-none",
        "c-pwc",
    ]


# ---------- 批量通过预检（任何失败不留写入） ----------


async def test_batch_preflight_rejects_high_risk_low_conf_and_writes_nothing(
    client, session_factory
):
    await _seed_queue(session_factory)
    url = "/api/review-workbench/batch-approve"

    resp = await client.post(
        url,
        json={"candidate_ids": ["c-high"], "actor": REVIEWER},
    )
    assert resp.status_code == 422
    assert "c-high" in resp.text

    resp = await client.post(
        url,
        json={"candidate_ids": ["c-pwc"], "actor": REVIEWER},
    )
    assert resp.status_code == 422

    # 高风险与合格候选混批：整批拒绝，合格候选仍 pending。
    resp = await client.post(
        url,
        json={"candidate_ids": ["c-atom-low", "c-high"], "actor": REVIEWER},
    )
    assert resp.status_code == 422

    async with session_factory() as session:
        for cid in ("c-high", "c-atom-low", "c-pwc"):
            cand = await session.get(SkillCandidate, cid)
            assert cand.state == "pending_review"
            assert cand.reviewed_at is None


async def test_batch_preflight_role_gate_is_per_candidate_wf(client, session_factory):
    await _seed_queue(session_factory)
    url = "/api/review-workbench/batch-approve"

    # WF-01 归 operations、WF-03 归 product_reviewer：混角色批双向拒绝。
    resp = await client.post(
        url,
        json={"candidate_ids": ["c-c1-low", "c-atom-low"], "actor": REVIEWER},
    )
    assert resp.status_code == 403
    resp = await client.post(
        url,
        json={"candidate_ids": ["c-c1-low", "c-atom-low"], "actor": OPS},
    )
    assert resp.status_code == 403

    # 不存在 / 非 pending。
    resp = await client.post(
        url,
        json={"candidate_ids": ["c-atom-low", "nope"], "actor": REVIEWER},
    )
    assert resp.status_code == 404
    resp = await client.post(
        url,
        json={"candidate_ids": ["c-applied"], "actor": REVIEWER},
    )
    assert resp.status_code == 409


# ---------- 批量通过 happy path：真实适配器、整批成败一致 ----------


async def _make_ps(session_factory, *, industry="general"):
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id="t1", status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id="t1",
            intake_id=intake.intake_id,
            industry_tag=industry,
            profile_snapshot={"f_a": "x"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


def _dim(i):
    return {
        "field_name": f"维度{i}",
        "role": "product_attribute",
        "source_route": "user_input",
        "confidence": 0.9,
        "source_ref": f"ref-{i}",
    }


async def _approved_pool(client, ps_id):
    body = {
        "dimensions": [_dim(1), _dim(2), _dim(3)],
        "actor": OPS,
        "target_atom_min": 15,
        "target_atom_max": 30,
    }
    resp = await client.post(f"/api/product-spaces/{ps_id}/field-pools", json=body)
    assert resp.status_code == 200, resp.text
    pool_id = resp.json()["pool_id"]
    gate = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    return pool.json()


def _deliver_body(ps_id, dims, contents, *, confidence):
    return {
        "skill_id": "CONFLICT-PRECHECK",
        "wf_id": "WF-03",
        "product_space_id": ps_id,
        "confidence": confidence,
        "candidates": [
            {
                "target_type": "atom_batch",
                "payload": {
                    "items": [
                        {
                            "content": content,
                            "dimension_id": dim,
                            "ai_risk": "low",
                            "evidence": f"依据 {content}",
                        }
                        for content, dim in zip(contents, dims, strict=True)
                    ]
                },
            }
        ],
        "actor": OPS,
    }


async def test_batch_approve_applies_two_low_risk_confident_candidates(
    client, session_factory
):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1, d2 = (d["dimension_id"] for d in pool["dimensions"][:2])

    first = await client.post(
        "/api/skill-runs",
        json=_deliver_body(ps_id, [d1, d2], ["温和不刺激", "每天两次"], confidence=0.9),
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        "/api/skill-runs",
        json=_deliver_body(ps_id, [d1, d2], ["清爽不紧绷", "晚间使用"], confidence=0.92),
    )
    ids = [first.json()["candidate_ids"][0], second.json()["candidate_ids"][0]]

    # OPS（WF-03 非裁决角色）不能批量通过。
    forb = await client.post(
        "/api/review-workbench/batch-approve",
        json={"candidate_ids": ids, "actor": OPS},
    )
    assert forb.status_code == 403

    ok = await client.post(
        "/api/review-workbench/batch-approve",
        json={"candidate_ids": ids, "reason": "批量通过", "actor": REVIEWER},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["count"] == 2
    assert {c["candidate_id"] for c in body["approved"]} == set(ids)
    assert all(c["state"] == "applied" for c in body["approved"])

    queue = await client.get(
        "/api/review-workbench/candidates",
        params=_params(REVIEWER, state="pending_review"),
    )
    assert queue.json()["total"] == 0

    # 两个 AtomBatch 各落 2 条 AtomCandidate（适配器规则一项未绕）。
    atoms = await client.get(f"/api/product-spaces/{ps_id}/atom-candidates")
    assert len(atoms.json()) == 4
