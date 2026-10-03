"""Q259 段7/8 动态信号 + PCP 重算候选 HumanGate API 集成测试。

覆盖：Q37 动态信号事件 CRUD（operations 写口 / query actor 读口）、
match advisory 回带（不改变规则裁决）、Q41/Q42 候选提交（Σ≤1.0 校验、
±recalc_step 幅度、同 PCP 单 pending）与批准/打回生效写回。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from app.platform.platform_adaptation.models import PcpTemplate
from app.platform.platform_adaptation.seeds import PCP_TEMPLATE_SEEDS
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.product_intake.models import ProductIntakeApplication, ProductSpace
from tests.integration.staff_tokens import acting_as, bearer, issue_write_token

OPS = {"id": "ops-1", "roles": ["operations"]}
NOBODY = {"id": "nobody-1", "roles": []}

EVENT = {
    "platform": "x_platform",
    "event_type": "platform_policy_change",
    "severity": "high",
    "effective_start": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
    "effective_end": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    "note": "平台政策变化预警",
}


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
    app.dependency_overrides[get_auth_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async with session_factory() as session:
        session.add_all([ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS])
        session.add_all(
            [
                PcpTemplate(
                    template_id=row["template_id"],
                    code=row["code"],
                    name=row["name"],
                    weights=row["weights"],
                )
                for row in PCP_TEMPLATE_SEEDS
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


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
        return ps.product_space_id, tenant


async def _make_pcp(client, ps_id, *, platform="x_platform", template="short_video"):
    resp = await client.post(
        f"/api/product-spaces/{ps_id}/pcp",
        json={"platform": platform, "template_code": template, "actor": OPS},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _tweak(weights: dict, delta: float = 0.05) -> dict:
    """键内再分配：goal 调 +delta、hook 调 -delta，Σ 保持 1（Q40 不破）。"""
    out = dict(weights)
    out["goal"] = round(out.get("goal", 0) + delta, 6)
    out["hook"] = round(out.get("hook", 0) - delta, 6)
    return out


# ---------- Q37 动态信号事件 CRUD ----------

async def test_event_crud_role_gate(client):
    # Q242：写口只认已验真令牌 ⇒ 越权＝换一枚没有 operations 的令牌。
    async with acting_as(client, ["product_reviewer"], staff_id="s-rev"):
        forbidden = await client.post(
            "/api/admin/platform-dynamic-events",
            json={"item": EVENT, "actor": NOBODY},
        )
        assert forbidden.status_code == 403

    resp = await client.post(
        "/api/admin/platform-dynamic-events",
        json={"item": EVENT, "actor": OPS},
    )
    assert resp.status_code == 201, resp.text
    ev = resp.json()
    assert ev["platform"] == "x_platform"
    assert ev["status"] == "active"
    assert ev["severity"] == "high"

    # 生效窗非法：end < start → 422
    bad = await client.post(
        "/api/admin/platform-dynamic-events",
        json={
            "item": {
                **EVENT,
                "effective_start": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
                "effective_end": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
            "actor": OPS,
        },
    )
    assert bad.status_code == 422

    # 读口：query actor 不带 operations → 403（Q118 口径）
    reader = await client.get(
        "/api/admin/platform-dynamic-events?actor_id=ops-1&roles=operations"
    )
    assert reader.status_code == 200
    assert len(reader.json()) == 1
    denied = await client.get(
        "/api/admin/platform-dynamic-events?actor_id=nobody-1&roles="
    )
    assert denied.status_code == 403

    # 更新 + 归档
    updated = await client.put(
        f"/api/admin/platform-dynamic-events/{ev['event_id']}",
        json={"item": {**EVENT, "severity": "medium"}, "actor": OPS},
    )
    assert updated.status_code == 200
    assert updated.json()["severity"] == "medium"

    archived = await client.request(
        "DELETE",
        f"/api/admin/platform-dynamic-events/{ev['event_id']}",
        json={"actor": OPS},
    )
    assert archived.status_code == 204
    gone = await client.get(
        "/api/admin/platform-dynamic-events?actor_id=ops-1&roles=operations&status=active"
    )
    assert gone.json() == []
    archived_list = await client.get(
        "/api/admin/platform-dynamic-events?actor_id=ops-1&roles=operations&status=archived"
    )
    assert len(archived_list.json()) == 1


# ---------- Q37 match advisory 回带 ----------

async def test_match_returns_active_events_advisory(session_factory, client):
    await client.post(
        "/api/admin/platform-dynamic-events",
        json={"item": EVENT, "actor": OPS},
    )
    # 生效窗外的旧事件（不影响当前 match）
    await client.post(
        "/api/admin/platform-dynamic-events",
        json={
            "item": {
                **EVENT,
                "platform": "x_platform",
                "effective_start": (datetime.now(UTC) - timedelta(days=60)).isoformat(),
                "effective_end": (datetime.now(UTC) - timedelta(days=30)).isoformat(),
            },
            "actor": OPS,
        },
    )
    hit = await client.get(
        "/api/admin/platform-rules/match?platform=x_platform&slot_type=main"
    )
    assert hit.status_code == 200
    assert hit.json()["effect"] is None  # 无规则命中 → effect None（Q36 native 不存）
    events = hit.json()["events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "platform_policy_change"

    miss = await client.get(
        "/api/admin/platform-rules/match?platform=y_platform&slot_type=main"
    )
    assert miss.json()["events"] == []


# ---------- Q41/Q42 PCP 重算候选 HumanGate ----------

async def test_candidate_submit_validation_and_pending_unique(session_factory, client):
    ps_id, _ = await _make_ps(session_factory)
    pcp = await _make_pcp(client, ps_id)

    proposed = _tweak(pcp["weights"], 0.05)
    resp = await client.post(
        "/api/admin/pcp-recalc/candidates",
        json={
            "pcp_id": pcp["pcp_id"],
            "proposed_weights": proposed,
            "change_list": [{"field": "goal", "old": 0.2, "new": 0.25, "reason": "recalc"}],
            "actor": OPS,
        },
    )
    assert resp.status_code == 201, resp.text
    cand = resp.json()
    assert cand["status"] == "pending"
    assert cand["source"] == "manual"
    assert cand["change_list"]  # 有实际变化才进对照单

    # 同 PCP 已有 pending → 409（partial unique index 双保险）
    again = await client.post(
        "/api/admin/pcp-recalc/candidates",
        json={"pcp_id": pcp["pcp_id"], "proposed_weights": proposed, "actor": OPS},
    )
    assert again.status_code == 409

    # 越权提交 → 403
    async with acting_as(client, ["product_reviewer"], staff_id="s-rev"):
        forbidden = await client.post(
            "/api/admin/pcp-recalc/candidates",
            json={"pcp_id": pcp["pcp_id"], "proposed_weights": proposed, "actor": NOBODY},
        )
        assert forbidden.status_code == 403

    # Σ>1 → 422（Q40 统一校验器）
    over = await client.post(
        "/api/admin/pcp-recalc/candidates",
        json={
            "pcp_id": pcp["pcp_id"],
            "proposed_weights": {**pcp["weights"], "goal": 0.95, "hook": 0.9},
            "actor": OPS,
        },
    )
    assert over.status_code == 422
    assert "weight_sum_exceeds_1" in over.json()["detail"]["violations"]


async def test_candidate_step_cap_and_approve_reject(session_factory, client):
    ps_id, _ = await _make_ps(session_factory)
    pcp = await _make_pcp(client, ps_id)

    # Q42：单项变化超出 ±0.05 → 422，重大变化走人工直编 PUT（无幅度限制）。
    # goal +0.1 / hook -0.1：Σ 保持 1，单项变化 0.1 > 0.05。
    big = {**pcp["weights"], "goal": pcp["weights"]["goal"] + 0.1, "hook": pcp["weights"]["hook"] - 0.1}
    overstep = await client.post(
        "/api/admin/pcp-recalc/candidates",
        json={"pcp_id": pcp["pcp_id"], "proposed_weights": big, "actor": OPS},
    )
    assert overstep.status_code == 422
    assert "recalc step exceeded" in overstep.json()["detail"]

    # 批准生效：写回 pcp_weight_tables + 清 template_code（Q42 人工直编语义）
    proposed = _tweak(pcp["weights"], 0.05)
    cand = (
        await client.post(
            "/api/admin/pcp-recalc/candidates",
            json={"pcp_id": pcp["pcp_id"], "proposed_weights": proposed, "actor": OPS},
        )
    ).json()
    approved = await client.post(
        f"/api/admin/pcp-recalc/candidates/{cand['candidate_id']}/approve",
        json={"actor": OPS},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    listed = await client.get(f"/api/product-spaces/{ps_id}/pcp")
    pcp_after = next(p for p in listed.json() if p["pcp_id"] == pcp["pcp_id"])
    assert pcp_after["weights"] == proposed
    assert pcp_after["template_code"] is None

    # pending 已释放 ⇒ 可再提交新候选
    again = await client.post(
        "/api/admin/pcp-recalc/candidates",
        json={"pcp_id": pcp["pcp_id"], "proposed_weights": proposed, "actor": OPS},
    )
    assert again.status_code == 201

    # 打回：reason 必填；打回后同 PCP 可再提
    cand2 = again.json()
    rejected = await client.post(
        f"/api/admin/pcp-recalc/candidates/{cand2['candidate_id']}/reject",
        json={"reason": "权重偏移方向有误", "actor": OPS},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["rejected_reason"] == "权重偏移方向有误"

    # 已终态候选再 approve / reject → 404
    stale_approve = await client.post(
        f"/api/admin/pcp-recalc/candidates/{cand['candidate_id']}/approve",
        json={"actor": OPS},
    )
    assert stale_approve.status_code == 404
    stale_reject = await client.post(
        f"/api/admin/pcp-recalc/candidates/{cand2['candidate_id']}/reject",
        json={"reason": "x", "actor": OPS},
    )
    assert stale_reject.status_code == 404

    # 读口列表 + 状态过滤（query actor 闸）
    all_cands = await client.get(
        "/api/admin/pcp-recalc/candidates?actor_id=ops-1&roles=operations"
    )
    assert all_cands.status_code == 200
    statuses = {c["status"] for c in all_cands.json()}
    assert statuses == {"approved", "rejected"}
    denied = await client.get(
        "/api/admin/pcp-recalc/candidates?actor_id=nobody-1&roles="
    )
    assert denied.status_code == 403
