"""段4 原子拓展（WF-03 确定性切片）API 集成测试。

覆盖 docs/08 M4 验收行：approveAtomGuard、AtomConflict、risk 双轨（Q17）、
critical 单条审（Q70）、证据 7 天超时可复活（Q18）、同义簇（Q19）、
产品事实原子引用数=1（line 11189）、Q20 生命周期、Q48 词表 CRUD。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from app.product.atom import service as atom_service
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import (
    G2Field,
    ProductIntakeApplication,
    ProductSpace,
)

REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
OPS = {"id": "ops-1", "roles": ["operations"]}
COMPLIANCE = {"id": "comp-1", "roles": ["internal_compliance"]}
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
                FPSourceRoute(
                    route="compliance_risk", name="合规风险面", sort_order=2
                ),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _make_ps(session_factory, *, sensitive=False, industry="general", tenant="t1"):
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id=tenant, status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id=tenant,
            intake_id=intake.intake_id,
            sensitive_industry=sensitive,
            industry_tag=industry,
            profile_snapshot={"f_a": "x"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


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


async def _approved_pool(
    client, ps_id, *, target_min=15, target_max=30, sensitive=False
):
    dims = [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)]
    if sensitive:
        dims.append(_dim(4, role="risk_control", source_route="compliance_risk"))
    body = {
        "dimensions": dims,
        "actor": OPS,
        "target_atom_min": target_min,
        "target_atom_max": target_max,
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


def _item(content, dimension_id, **kw):
    return {"content": content, "dimension_id": dimension_id, **kw}


async def _submit_batch(client, ps_id, items, **extra):
    body = {"items": items, "actor": OPS, **extra}
    return await client.post(f"/api/product-spaces/{ps_id}/atom-batches", json=body)


async def _wordlist(client, word, *, level, action="ban", target=None, industry=None, actor=OPS):
    item = {"word": word, "level": level, "action": action}
    if target:
        item["downgrade_target"] = target
    if industry:
        item["industry"] = industry
    return await client.post(
        "/api/admin/compliance-wordlist", json={"item": item, "actor": actor}
    )


# ---------- 批次前置与 Q14/Q15 ----------

async def test_batch_requires_approved_pool(client, session_factory):
    ps_id = await _make_ps(session_factory)
    # 无池 → 404
    dim_id = "does-not-exist"
    resp = await _submit_batch(client, ps_id, [_item("原子A", dim_id, evidence="e")])
    assert resp.status_code == 404

    # 有池但未过 Gate → 409
    await client.post(
        f"/api/product-spaces/{ps_id}/field-pools",
        json={"dimensions": [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)], "actor": OPS},
    )
    pool = (await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")).json()
    blocked = await _submit_batch(
        client, ps_id, [_item("原子A", pool["dimensions"][0]["dimension_id"], evidence="e")]
    )
    assert blocked.status_code == 409


async def test_batch_size_defaults_q14_and_override(client, session_factory):
    ps_id = await _make_ps(session_factory, sensitive=True, industry="medical")
    pool = await _approved_pool(client, ps_id, sensitive=True)
    dim_id = pool["dimensions"][0]["dimension_id"]

    over = [_item(f"敏感原子{i}", dim_id, evidence="e") for i in range(21)]
    assert (await _submit_batch(client, ps_id, over)).status_code == 422

    # 拓展时可显式覆盖批次上限（Q14）。
    ok = await _submit_batch(client, ps_id, over, batch_size=21)
    assert ok.status_code == 200
    assert ok.json()["batch_size"] == 21

    # 非敏感默认 50：51 条拒，50 条过。
    ps2 = await _make_ps(session_factory)
    pool2 = await _approved_pool(client, ps2)
    d2 = pool2["dimensions"][0]["dimension_id"]
    assert (
        await _submit_batch(client, ps2, [_item(f"原子{i}", d2, evidence="e") for i in range(51)])
    ).status_code == 422


async def test_target_reached_stops_ai_but_manual_allowed_q15(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id, target_min=1, target_max=1)
    d1, d2 = (d["dimension_id"] for d in pool["dimensions"][:2])

    first = await _submit_batch(client, ps_id, [_item("原子一", d1, evidence="e")])
    cid = first.json()["candidates"][0]["candidate_id"]
    approved = await client.post(
        f"/api/atom-candidates/{cid}/approve", json={"actor": REVIEWER}
    )
    assert approved.status_code == 200

    # AI 自动拓展到达上限 → 409；手动批次不受限（Q15）。
    ai = await _submit_batch(client, ps_id, [_item("原子二", d2, evidence="e")])
    assert ai.status_code == 409
    manual = await _submit_batch(
        client, ps_id, [_item("原子二手动", d2, evidence="e")], source="manual"
    )
    assert manual.status_code == 200


async def test_same_batch_dedup_and_bad_dimension(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]

    dup = await _submit_batch(
        client,
        ps_id,
        [_item("同一个词", d1, evidence="e"), _item("  同一个词 ", d1, evidence="e2")],
    )
    assert dup.status_code == 422

    bad_dim = await _submit_batch(
        client, ps_id, [_item("原子", "wrong-dimension-id", evidence="e")]
    )
    assert bad_dim.status_code == 422


# ---------- line 11189 产品事实原子 ----------

async def test_fact_atom_value_globally_unique(client, session_factory):
    ps1 = await _make_ps(session_factory, tenant="t1")
    pool1 = await _approved_pool(client, ps1)
    ps2 = await _make_ps(session_factory, tenant="t2")
    pool2 = await _approved_pool(client, ps2)

    r1 = await _submit_batch(
        client, ps1,
        [_item("10ml", pool1["dimensions"][0]["dimension_id"],
               fact_type="capacity", evidence="包装标注")],
    )
    assert r1.status_code == 200

    # 跨产品（跨租户）同款事实值禁止复用 → 409。
    r2 = await _submit_batch(
        client, ps2,
        [_item("10ml", pool2["dimensions"][0]["dimension_id"],
               fact_type="capacity", evidence="包装标注")],
    )
    assert r2.status_code == 409

    # 普通表达原子不受此约束。
    r3 = await _submit_batch(
        client, ps2,
        [_item("10ml", pool2["dimensions"][1]["dimension_id"], evidence="评论依据")],
    )
    assert r3.status_code == 200


# ---------- Q17 risk 双轨 + AtomConflict ----------

async def test_wordlist_critical_ban_blocks_and_reject_audits(client, session_factory):
    await _wordlist(client, "禁用词", level="critical", action="ban")
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]

    resp = await _submit_batch(
        client, ps_id,
        [_item("这是一句含禁用词的表达", d1, evidence="依据", ai_risk="low")],
    )
    cand = resp.json()["candidates"][0]
    assert cand["risk_level"] == "critical"
    assert cand["risk_source"] == "wordlist"
    conflict_types = {c["type"]: c["status"] for c in cand["conflicts"]}
    assert conflict_types == {"disabled_expression": "blocked"}

    # blocked 冲突下过 Guard → 409。
    gated = await client.post(
        f"/api/atom-candidates/{cand['candidate_id']}/approve",
        json={"actor": REVIEWER},
    )
    assert gated.status_code == 409
    assert "blocked_conflict" in gated.json()["detail"]

    # critical 驳回（合规审计动作）。
    rejected = await client.post(
        f"/api/atom-candidates/{cand['candidate_id']}/reject",
        json={"reason": "banned expression", "actor": REVIEWER},
    )
    assert rejected.status_code == 200


async def test_high_risk_single_review_q70_and_evidence_conflict(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    d2 = pool["dimensions"][1]["dimension_id"]

    # high 无证据 → pending_evidence + 双冲突，批量/单条均不能过。
    no_ev = (await _submit_batch(client, ps_id, [_item("高风险表达", d1, ai_risk="high")])).json()
    c_noev = no_ev["candidates"][0]
    assert c_noev["status"] == "pending_evidence"
    assert {c["type"] for c in c_noev["conflicts"]} == {
        "high_risk_single_review",
        "evidence_required",
    }

    # high 带证据 → 单条审可过（Q70），批量审拒绝。
    batch = await _submit_batch(
        client, ps_id,
        [
            _item("高风险甲", d1, ai_risk="high", evidence="ev"),
            _item("高风险乙", d2, ai_risk="high", evidence="ev"),
        ],
    )
    c1, c2 = batch.json()["candidates"]
    bulk = await client.post(
        "/api/atom-candidates/batch-approve",
        json={"candidate_ids": [c1["candidate_id"], c2["candidate_id"]], "actor": REVIEWER},
    )
    assert bulk.status_code == 409
    assert "bulk_high_critical_forbidden" in bulk.json()["detail"]

    single = await client.post(
        f"/api/atom-candidates/{c1['candidate_id']}/approve", json={"actor": REVIEWER}
    )
    assert single.status_code == 200


async def test_human_downgrade_allowed_for_ai_but_not_wordlist_q17(client, session_factory):
    await _wordlist(client, "强制词", level="high", action="downgrade", target="低替代表述")
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1, d2 = (d["dimension_id"] for d in pool["dimensions"][:2])

    forced = (await _submit_batch(
        client, ps_id, [_item("含强制词的表达", d1, evidence="ev", ai_risk="low")]
    )).json()["candidates"][0]
    assert forced["risk_level"] == "high"
    forbid = await client.post(
        f"/api/atom-candidates/{forced['candidate_id']}/risk-override",
        json={"level": "low", "reason": "人工认为不高", "actor": REVIEWER},
    )
    assert forbid.status_code == 409

    ai_high = (await _submit_batch(
        client, ps_id, [_item("AI 判高的表达", d2, ai_risk="high", evidence="ev")]
    )).json()["candidates"][0]
    down = await client.post(
        f"/api/atom-candidates/{ai_high['candidate_id']}/risk-override",
        json={"level": "low", "reason": "复核无风险", "actor": REVIEWER},
    )
    assert down.status_code == 200
    assert down.json()["risk_level"] == "low"
    assert down.json()["risk_source"] == "manual"
    open_conflicts = [
        c for c in down.json()["conflicts"] if c["resolved_at"] is None
    ]
    assert open_conflicts == []


# ---------- Q18 证据补传 / 超时 / 复活 ----------

async def test_evidence_supplement_timeout_sweep_and_revive(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1, d2 = (d["dimension_id"] for d in pool["dimensions"][:2])

    batch = await _submit_batch(
        client,
        ps_id,
        [
            _item("待补证据甲", d1, ai_risk="high"),
            _item("待补证据乙", d2, ai_risk="high"),
        ],
    )
    c_sup, c_timeout = batch.json()["candidates"]
    assert c_sup["status"] == "pending_evidence"
    assert c_sup["evidence_due_at"] is not None

    # 补证据 → pending_review，evidence_required 解除。
    sup = await client.post(
        f"/api/atom-candidates/{c_sup['candidate_id']}/evidence",
        json={"evidence": "后补的依据", "actor": OPS},
    )
    assert sup.status_code == 200
    assert sup.json()["status"] == "pending_review"
    open_conflicts = [c for c in sup.json()["conflicts"] if c["resolved_at"] is None]
    assert {c["type"] for c in open_conflicts} == {"high_risk_single_review"}

    # 超时扫描（系统动作，调度器 M10 接）：补证据的那条不受影响，另一条超时驳回。
    async with session_factory() as session:
        count = await atom_service.sweep_evidence_timeouts(
            session, datetime.now(UTC) + timedelta(days=8)
        )
        await session.commit()
    assert count == 1

    # 可复活重走审核；无证据 → 重新 pending_evidence + 新期限。
    revive = await client.post(
        f"/api/atom-candidates/{c_timeout['candidate_id']}/revive",
        json={"actor": OPS},
    )
    assert revive.status_code == 200
    data = revive.json()
    assert data["status"] == "pending_evidence"
    assert data["reject_reason"] is None


# ---------- Q19 同义簇 ----------

async def test_cluster_resolve_merges_aliases_into_keeper_atom(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]

    batch = await _submit_batch(
        client, ps_id,
        [
            _item("拍照清晰", d1, evidence="评论A", affinity=0.9, cluster_id="cl-1"),
            _item("成像清楚", d1, evidence="评论B", affinity=0.6, cluster_id="cl-1"),
        ],
    )
    keeper, other = batch.json()["candidates"]
    resolved = await client.post(
        "/api/atom-clusters/cl-1/resolve",
        json={"keeper_candidate_id": keeper["candidate_id"], "actor": REVIEWER},
    )
    assert resolved.status_code == 200
    assert resolved.json()["merged"] == [other["candidate_id"]]

    atom = await client.post(
        f"/api/atom-candidates/{keeper['candidate_id']}/approve",
        json={"actor": REVIEWER},
    )
    assert atom.status_code == 200
    assert "成像清楚" in atom.json()["aliases"]


# ---------- Q20 正式原子生命周期 ----------

async def test_atom_lifecycle_roles_and_transitions(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    cid = (await _submit_batch(client, ps_id, [_item("普通原子", d1, evidence="e")])).json()["candidates"][0]["candidate_id"]
    atom_id = (
        await client.post(f"/api/atom-candidates/{cid}/approve", json={"actor": REVIEWER})
    ).json()["atom_id"]

    # 冻结=运营；审核员无权。
    assert (await client.post(f"/api/atoms/{atom_id}/freeze", json={"actor": REVIEWER})).status_code == 403
    frozen = await client.post(f"/api/atoms/{atom_id}/freeze", json={"actor": OPS})
    assert frozen.json()["status"] == "frozen"
    # 解冻不重审，直接回 approved（Q20）。
    assert (await client.post(f"/api/atoms/{atom_id}/unfreeze", json={"actor": OPS})).json()["status"] == "approved"

    # 合规暂停/恢复=internal_compliance。
    assert (await client.post(f"/api/atoms/{atom_id}/compliance-suspend", json={"actor": OPS})).status_code == 403
    await client.post(f"/api/atoms/{atom_id}/compliance-suspend", json={"actor": COMPLIANCE})
    assert (await client.post(f"/api/atoms/{atom_id}/compliance-resume", json={"actor": COMPLIANCE})).json()["status"] == "approved"

    # approved 态原子不能直接归档。
    assert (await client.post(f"/api/atoms/{atom_id}/archive", json={"actor": OPS})).status_code == 409

    # 废弃→归档；废弃恢复=新原子重审（无原地复活）。
    await client.post(f"/api/atoms/{atom_id}/deprecate", json={"actor": OPS})
    assert (await client.post(f"/api/atoms/{atom_id}/archive", json={"actor": OPS})).json()["status"] == "archived"


async def test_atom_reject_and_archive_path(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    cid = (await _submit_batch(client, ps_id, [_item("待废原子", d1, evidence="e")])).json()["candidates"][0]["candidate_id"]
    atom_id = (
        await client.post(f"/api/atom-candidates/{cid}/approve", json={"actor": REVIEWER})
    ).json()["atom_id"]

    rejected = await client.post(
        f"/api/atoms/{atom_id}/reject",
        json={"reason": "不再使用", "actor": REVIEWER},
    )
    assert rejected.json()["status"] == "rejected"
    archived = await client.post(f"/api/atoms/{atom_id}/archive", json={"actor": OPS})
    assert archived.json()["status"] == "archived"


# ---------- Q48 词表 CRUD ----------

async def test_wordlist_crud_roles_and_archived_not_matched(client, session_factory):
    forbidden = await _wordlist(client, "词", level="critical", actor=NOBODY)
    assert forbidden.status_code == 403

    # downgrade 必须带 downgrade_target → 422。
    bad = await _wordlist(client, "降级词", level="high", action="downgrade", actor=OPS)
    assert bad.status_code == 422

    entry = (await _wordlist(
        client, "临时词", level="critical", action="ban", actor=COMPLIANCE
    )).json()
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    hit = await _submit_batch(client, ps_id, [_item("含临时词", d1, evidence="e")])
    assert hit.json()["candidates"][0]["risk_source"] == "wordlist"

    # 归档（DELETE 软删）后不再参与匹配。
    deleted = await client.request(
        "DELETE",
        f"/api/admin/compliance-wordlist/{entry['entry_id']}",
        json={"actor": OPS},
    )
    assert deleted.status_code == 200
    miss = await _submit_batch(client, ps_id, [_item("另一句含临时词", d1, evidence="e")])
    assert miss.json()["candidates"][0]["risk_source"] == "ai"
