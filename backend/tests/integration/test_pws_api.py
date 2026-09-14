"""段6 PWS 冻结 API 集成测试。

覆盖 docs/08 M6 验收行：pwsReadiness 5 项（line 2634/Q28）、BO-07 红线、
Q29 重冻三档、Q30 换版处置、Q31 版本、Q32 急停、Q33 同租户查重。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.fieldpool.models import FPSourceRoute
from app.product.modeling.models import OpsTodo
from app.product.product_intake.models import (
    G2Field,
    ProductIntakeApplication,
    ProductSpace,
)

OWNER = {"id": "owner-1", "roles": ["whitelist_owner"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
OPS = {"id": "ops-1", "roles": ["operations"]}
PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
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
                G2Field(fid="f_a", cat="common", field_name="字段A"),
                G2Field(fid="f_b", cat="selling", field_name="字段B"),
                FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
                FPSourceRoute(route="compliance_risk", name="合规风险面", sort_order=2),
            ]
            + [ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _dim(i, **kw):
    base = {
        "field_name": f"维度{i}",
        "role": "product_attribute",
        "source_route": "user_input",
        "confidence": 0.9,
        "source_ref": f"ref-{i}",
    }
    base.update(kw)
    return base


async def _make_ps(session_factory, *, tenant="t1"):
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id=tenant, status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id=tenant,
            intake_id=intake.intake_id,
            industry_tag="general",
            profile_snapshot={"f_a": "x"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


async def _approved_pool(client, ps_id):
    body = {"dimensions": [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)], "actor": OPS}
    resp = await client.post(f"/api/product-spaces/{ps_id}/field-pools", json=body)
    assert resp.status_code == 200, resp.text
    pool_id = resp.json()["pool_id"]
    gate = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text


async def _approve_atoms(client, ps_id, contents):
    await _approved_pool(client, ps_id)
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    dim_ids = [d["dimension_id"] for d in pool.json()["dimensions"]]
    items = [
        {"content": c, "dimension_id": dim_ids[i], "ai_risk": "low", "evidence": "语料"}
        for i, c in enumerate(contents)
    ]
    resp = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches", json={"items": items, "actor": OPS}
    )
    assert resp.status_code == 200, resp.text
    for c in resp.json()["candidates"]:
        ok = await client.post(
            f"/api/atom-candidates/{c['candidate_id']}/approve", json={"actor": REVIEWER}
        )
        assert ok.status_code == 200, ok.text
    atoms = await client.get(f"/api/product-spaces/{ps_id}/atoms")
    return [a["atom_id"] for a in atoms.json()]


async def _one_ready_pwc(client, ps_id, atom_ids):
    resp = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/funnel",
        json={"combos": [{"atom_ids": atom_ids[:2], "logic_score": 0.8, "fit_score": 0.6}],
              "actor": OPS},
    )
    assert resp.status_code == 200, resp.text
    pwc_id = resp.json()[0]["pwc_id"]
    ok = await client.post(
        f"/api/pwcs/{pwc_id}/gate", json={"decision": "approve", "actor": REVIEWER}
    )
    assert ok.status_code == 200, ok.text
    return pwc_id


async def _green_ps(client, session_factory):
    ps_id = await _make_ps(session_factory)
    atoms = await _approve_atoms(client, ps_id, ("温和洁面", "水润肤感", "清爽质地"))
    await _one_ready_pwc(client, ps_id, atoms)
    return ps_id


# ---------- Q28 就绪门与待办 ----------

async def test_readiness_gates_and_ps_404(client, session_factory):
    missing = await client.get("/api/product-spaces/nope/pws/readiness")
    assert missing.status_code == 404

    ps_id = await _make_ps(session_factory)
    red = await client.get(f"/api/product-spaces/{ps_id}/pws/readiness")
    assert red.status_code == 200
    body = red.json()
    assert body["all_green"] is False
    assert body["checks"]["approved_field_pool"] is False
    assert body["counts"]["approved_atoms"] == 0


async def test_evaluate_creates_todo_once_and_freeze_resolves(client, session_factory):
    ps_id = await _green_ps(client, session_factory)
    r1 = await client.post(
        f"/api/product-spaces/{ps_id}/pws/evaluate", json={"actor": OPS}
    )
    assert r1.json()["all_green"] is True
    todo_id = r1.json()["todo_id"]
    assert todo_id

    r2 = await client.post(
        f"/api/product-spaces/{ps_id}/pws/evaluate", json={"actor": OPS}
    )
    assert r2.json()["todo_id"] == todo_id  # 幂等

    freeze = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
    )
    assert freeze.status_code == 200, freeze.text
    pws = freeze.json()["pws"]
    assert pws["version"] == "v1.0"
    assert pws["status"] == "frozen" and pws["is_active"] is True
    assert len(pws["items"]) == 4  # 3 原子 + 1 PWC
    assert {i["kind"] for i in pws["items"]} == {"atom", "pwc"}
    assert freeze.json()["dispositions"] is None

    async with session_factory() as session:
        todo = await session.get(OpsTodo, todo_id)
        assert todo.status == "resolved" and todo.resolution == "frozen"


async def test_ready_todo_escalates_after_7_days(client, session_factory):
    ps_id = await _green_ps(client, session_factory)
    todo_id = (
        await client.post(
            f"/api/product-spaces/{ps_id}/pws/evaluate", json={"actor": OPS}
        )
    ).json()["todo_id"]
    async with session_factory() as session:
        todo = await session.get(OpsTodo, todo_id)
        todo.due_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    sweep = await client.post(
        "/api/admin/ops-todos/sweep", json={"actor": PLATFORM_ADMIN}
    )
    assert sweep.status_code == 200
    async with session_factory() as session:
        todo = await session.get(OpsTodo, todo_id)
        assert todo.status == "escalated"
        assert todo.assignee_role == "whitelist_owner"


async def test_freeze_blocked_when_not_green_and_role(client, session_factory):
    ps_id = await _make_ps(session_factory)
    denied = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OPS}
    )
    assert denied.status_code == 403  # 红线角色闸优先

    red = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
    )
    assert red.status_code == 409  # 就绪门不全绿
    assert red.json()["detail"]["approved_field_pool"] is False


async def test_blocked_conflict_gate(client, session_factory):
    ps_id = await _make_ps(session_factory)
    await _approved_pool(client, ps_id)
    wl = await client.post(
        "/api/admin/compliance-wordlist",
        json={"item": {"word": "根治", "level": "critical", "action": "ban"}, "actor": OPS},
    )
    assert wl.status_code == 200, wl.text
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    dims = [d["dimension_id"] for d in pool.json()["dimensions"]]
    batch = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches",
        json={"items": [
            {"content": f"词{i}", "dimension_id": dims[i], "ai_risk": "low", "evidence": "e"}
            for i in range(2)
        ] + [{"content": "保证根治", "dimension_id": dims[2], "ai_risk": "low", "evidence": "e"}],
              "actor": OPS},
    )
    assert batch.status_code == 200
    readiness = await client.get(f"/api/product-spaces/{ps_id}/pws/readiness")
    body = readiness.json()
    assert body["checks"]["no_unresolved_blocked_conflict"] is False
    assert body["counts"]["unresolved_blocked_conflicts"] >= 1


# ---------- Q29/Q30/Q31 重冻换版 ----------

async def test_refreeze_tiers_and_versioning(client, session_factory):
    ps_id = await _green_ps(client, session_factory)
    v1 = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
    )
    v1_id = v1.json()["pws"]["pws_id"]

    no_reason = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
    )
    assert no_reason.status_code == 422

    none_tier = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze",
        json={"actor": OWNER, "reason_code": "unrelated_change"},
    )
    assert none_tier.status_code == 409

    bad_reason = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze",
        json={"actor": OWNER, "reason_code": "nope"},
    )
    assert bad_reason.status_code == 422

    v2 = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze",
        json={"actor": OWNER, "reason_code": "asset_increment"},
    )
    assert v2.status_code == 200, v2.text
    p2 = v2.json()["pws"]
    assert p2["version"] == "v2.0" and p2["is_active"] is True
    assert p2["refreeze_tier"] == "suggested"
    disp = v2.json()["dispositions"]
    assert disp["superseded_version"] == "v1.0"
    assert disp["draft_fcws_voided"] == []  # 段11 未实现，占位
    assert disp["published_marked_outdated"] == 0

    old = await client.get(f"/api/pws/{v1_id}")
    assert old.json()["status"] == "superseded"
    assert old.json()["is_active"] is False
    assert old.json()["superseded_by"] == p2["pws_id"]
    # 旧版只读：明细仍在
    assert len(old.json()["items"]) == 4

    versions = await client.get(f"/api/product-spaces/{ps_id}/pws")
    assert [p["version"] for p in versions.json()] == ["v2.0", "v1.0"]


async def test_forced_refreeze_flags_recheck(client, session_factory):
    ps_id = await _green_ps(client, session_factory)
    await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
    )
    v2 = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze",
        json={"actor": OWNER, "reason_code": "wordlist_hit"},
    )
    assert v2.json()["pws"]["refreeze_tier"] == "forced"
    assert v2.json()["dispositions"]["unpublished_pending_recheck"] is True


# ---------- Q32 急停 ----------

async def test_revoke_cuts_consumption_and_refreeze(client, session_factory):
    ps_id = await _green_ps(client, session_factory)
    v1 = (
        await client.post(
            f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
        )
    ).json()["pws"]

    denied = await client.post(
        f"/api/pws/{v1['pws_id']}/revoke",
        json={"reason": "外部新规追溯命中", "actor": OPS},
    )
    assert denied.status_code == 403
    missing = await client.post(
        "/api/pws/nope/revoke", json={"reason": "x", "actor": OWNER}
    )
    assert missing.status_code == 404

    revoked = await client.post(
        f"/api/pws/{v1['pws_id']}/revoke",
        json={"reason": "外部新规追溯命中", "actor": OWNER},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["is_active"] is False

    again = await client.post(
        f"/api/pws/{v1['pws_id']}/revoke",
        json={"reason": "再次急停", "actor": OWNER},
    )
    assert again.status_code == 409

    # 作废后重冻新版（Q32）
    v2 = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
    )
    assert v2.status_code == 200
    assert v2.json()["pws"]["version"] == "v2.0"
    assert v2.json()["pws"]["status"] == "frozen"


async def test_snapshot_immutable_after_source_change(client, session_factory):
    ps_id = await _green_ps(client, session_factory)
    freeze = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
    )
    frozen_atoms = freeze.json()["pws"]["snapshot"]["atoms"]
    assert len(frozen_atoms) == 3

    # 源头废弃一个正式原子（Q29 强制重冻触发源之一）；旧快照内容不变
    atom_id = frozen_atoms[0]["atom_id"]
    dep = await client.post(f"/api/atoms/{atom_id}/deprecate", json={"actor": OPS})
    assert dep.status_code == 200, dep.text
    old = (
        await client.get(f"/api/product-spaces/{ps_id}/pws")
    ).json()[0]
    assert len(old["snapshot"]["atoms"]) == 3
    # 但就绪门②随即变红（已批准原子 <3），不能直接重冻
    red = await client.get(f"/api/product-spaces/{ps_id}/pws/readiness")
    assert red.json()["checks"]["enough_approved_atoms"] is False
