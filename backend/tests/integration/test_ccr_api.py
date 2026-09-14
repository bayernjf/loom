"""段10 合规清洗 API 集成测试。

覆盖 docs/08 M7 验收行：三关卡同源 Q48 词库 / block_required 一票否决 /
Q49 法审待办卡 Guard⑥ / Q50 国家>平台>底座优先序 / Q51 词表生效即扫。
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
COMPLIANCE = {"id": "ic-1", "roles": ["internal_compliance"]}
NOBODY = {"id": "nobody-1", "roles": []}
PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}


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


async def _make_ps(session_factory, *, tenant="t1", industry="general", sensitive=False):
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id=tenant, status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id=tenant,
            intake_id=intake.intake_id,
            industry_tag=industry,
            sensitive_industry=sensitive,
            profile_snapshot={"f_a": "x"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


async def _freeze(
    client,
    ps_id,
    contents=("温和洁面", "水润肤感", "清爽质地"),
    *,
    risk_control=False,
):
    dims = [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)]
    if risk_control:
        # Q11：敏感行业字段池必须含 risk_control 维度
        dims.append(_dim(4, role="risk_control", fid=None))
    body = {"dimensions": dims, "actor": OPS}
    pool = await client.post(f"/api/product-spaces/{ps_id}/field-pools", json=body)
    assert pool.status_code == 200, pool.text
    pool_id = pool.json()["pool_id"]
    gate_resp = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate_resp.status_code == 200, gate_resp.text
    cur = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    dim_ids = [d["dimension_id"] for d in cur.json()["dimensions"]]
    items = [
        {"content": c, "dimension_id": dim_ids[i], "ai_risk": "low", "evidence": "语料"}
        for i, c in enumerate(contents)
    ]
    batch = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches", json={"items": items, "actor": OPS}
    )
    assert batch.status_code == 200, batch.text
    for c in batch.json()["candidates"]:
        await client.post(
            f"/api/atom-candidates/{c['candidate_id']}/approve", json={"actor": REVIEWER}
        )
    atoms = (await client.get(f"/api/product-spaces/{ps_id}/atoms")).json()
    atom_ids = [a["atom_id"] for a in atoms]
    funnel = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/funnel",
        json={"combos": [{"atom_ids": atom_ids[:2], "logic_score": 0.8, "fit_score": 0.6}],
              "actor": OPS},
    )
    assert funnel.status_code == 200, funnel.text
    pwc_id = funnel.json()[0]["pwc_id"]
    await client.post(f"/api/pwcs/{pwc_id}/gate", json={"decision": "approve", "actor": REVIEWER})
    freeze = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
    )
    assert freeze.status_code == 200, freeze.text
    return freeze.json()["pws"]


# ---------- CP-LAW 敏感领域清单 CRUD ----------

async def test_domain_crud_and_role(client):
    denied = await client.post(
        "/api/admin/cp-law-domains",
        json={"item": {"code": "diet", "name": "膳食"}, "actor": OPS},
    )
    assert denied.status_code == 403

    created = await client.post(
        "/api/admin/cp-law-domains",
        json={"item": {"code": "diet", "name": "膳食补充"}, "actor": COMPLIANCE},
    )
    assert created.status_code == 200, created.text
    domain_id = created.json()["domain_id"]

    dup = await client.post(
        "/api/admin/cp-law-domains",
        json={"item": {"code": "diet", "name": "x"}, "actor": COMPLIANCE},
    )
    assert dup.status_code == 409

    listed = await client.get("/api/admin/cp-law-domains")
    assert any(d["code"] == "diet" for d in listed.json())

    archived = await client.request(
        "DELETE", f"/api/admin/cp-law-domains/{domain_id}", json={"actor": COMPLIANCE}
    )
    assert archived.status_code == 200
    active = await client.get("/api/admin/cp-law-domains")
    assert all(d["code"] != "diet" for d in active.json())


# ---------- 同源词库 + block_required 一票否决 ----------

async def test_ccr_clean_blocked_and_append_only(client, session_factory):
    ps_id = await _make_ps(session_factory)
    # 冻结时词库无此词（Q51 典型场景：词条后加，旧快照仍含该词）
    pws = await _freeze(client, ps_id, contents=("温和根治护理", "水润肤感", "清爽质地"))

    missing = await client.post("/api/pws/nope/ccr/run", json={"actor": COMPLIANCE})
    assert missing.status_code == 404

    run1 = await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    assert run1.status_code == 200, run1.text
    assert run1.json()["report"]["status"] == "clean"
    assert run1.json()["report"]["block_required"] is False
    assert run1.json()["law_review"] is None

    # 冻结后新增 ban 词条（Q51 同时触发重冻待办），再跑段10 → 一票否决
    wl = await client.post(
        "/api/admin/compliance-wordlist",
        json={"item": {"word": "根治", "level": "critical", "action": "ban"}, "actor": OPS},
    )
    assert wl.status_code == 200
    run2 = await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    blocked = run2.json()["report"]
    assert blocked["status"] == "blocked" and blocked["block_required"] is True
    assert blocked["hits"]["bans"][0]["word"] == "根治"

    # 历史报告不可 mutate：两行都在（PT-COMPLIANCE-V2.0）
    reports = (await client.get(f"/api/pws/{pws['pws_id']}/ccr")).json()
    assert len(reports) == 2

    gate = await client.get(f"/api/pws/{pws['pws_id']}/ccr/gate")
    body = gate.json()
    assert body["block_required"] is True
    assert body["cleaning_passed"] is False
    assert body["law_review_required"] is False


async def test_superseded_snapshot_not_cleanable(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze",
        json={"actor": OWNER, "reason_code": "asset_increment"},
    )
    resp = await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    assert resp.status_code == 409


# ---------- CLAIM-DOWNGRADE：降级只出建议、人工 approval ----------

async def test_downgrade_suggestion_requires_approval(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id, contents=("治愈修护", "水润肤感", "清爽质地"))
    wl = await client.post(
        "/api/admin/compliance-wordlist",
        json={"item": {
            "word": "治愈", "level": "high", "action": "downgrade",
            "downgrade_target": "感受改善",
        }, "actor": OPS},
    )
    assert wl.json()["layer"] == "base"

    run = await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    report = run.json()["report"]
    assert report["status"] == "downgrade_pending"
    assert report["hits"]["downgrades"][0]["downgrade_target"] == "感受改善"
    ccr_id = report["ccr_id"]

    gate = (await client.get(f"/api/pws/{pws['pws_id']}/ccr/gate")).json()
    assert gate["cleaning_passed"] is False  # 建议未批准前不放行

    denied = await client.post(
        f"/api/ccr/{ccr_id}/approve-downgrades", json={"actor": OPS}
    )
    assert denied.status_code == 403
    approved = await client.post(
        f"/api/ccr/{ccr_id}/approve-downgrades", json={"actor": COMPLIANCE}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    gate = (await client.get(f"/api/pws/{pws['pws_id']}/ccr/gate")).json()
    assert gate["cleaning_passed"] is True and gate["block_required"] is False

    again = await client.post(
        f"/api/ccr/{ccr_id}/approve-downgrades", json={"actor": COMPLIANCE}
    )
    assert again.status_code == 409


# ---------- Q50 国家>平台>底座；分市场独立判 ----------

async def test_q50_layer_precedence_per_market(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id, contents=("焕白修护", "水润肤感", "清爽质地"))
    await client.post(
        "/api/admin/compliance-wordlist",
        json={"item": {
            "word": "焕白", "level": "high", "action": "downgrade",
            "downgrade_target": "提亮", "layer": "base",
        }, "actor": OPS},
    )
    await client.post(
        "/api/admin/compliance-wordlist",
        json={"item": {
            "word": "焕白", "level": "critical", "action": "ban",
            "country": "US", "layer": "country",
        }, "actor": OPS},
    )

    us = await client.post(
        f"/api/pws/{pws['pws_id']}/ccr/run", json={"country": "US", "actor": COMPLIANCE}
    )
    assert us.json()["report"]["status"] == "blocked"
    assert us.json()["report"]["hits"]["bans"][0]["layer"] == "country"

    cn = await client.post(
        f"/api/pws/{pws['pws_id']}/ccr/run", json={"country": "CN", "actor": COMPLIANCE}
    )
    assert cn.json()["report"]["status"] == "downgrade_pending"


# ---------- Q49 法审自动触发 + 卡 Guard⑥ ----------

async def test_law_review_trigger_decision_and_sla(client, session_factory):
    # 敏感领域清单（测试库不走迁移种子，经 API 建）
    await client.post(
        "/api/admin/cp-law-domains",
        json={"item": {"code": "medical", "name": "医疗健康"}, "actor": COMPLIANCE},
    )
    ps_id = await _make_ps(session_factory, industry="medical")
    pws = await _freeze(client, ps_id, contents=("温和护理", "水润肤感", "清爽质地"), risk_control=True)

    run = await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    law = run.json()["law_review"]
    assert law is not None and law["status"] == "pending" and law["domain"] == "medical"
    law_id = law["law_review_id"]

    # 幂等：再跑不重开
    run2 = await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    assert run2.json()["law_review"]["law_review_id"] == law_id

    gate = (await client.get(f"/api/pws/{pws['pws_id']}/ccr/gate")).json()
    assert gate["law_review_required"] is True
    assert gate["law_review_passed"] is False  # Guard⑥ 不放行

    # 待办派给 internal_compliance，48h due；sweep 升级链路复用通用待办
    from sqlalchemy import select as _select

    async with session_factory() as session:
        todo = (
            await session.scalars(
                _select(OpsTodo).where(
                    OpsTodo.todo_type == "law_review", OpsTodo.entity_id == law_id
                )
            )
        ).first()
        assert todo is not None
        assert todo.assignee_role == "internal_compliance"
        due = todo.due_at
        if due.tzinfo is not None:
            due = due.replace(tzinfo=None)
        assert (due - datetime.now(UTC).replace(tzinfo=None)) > timedelta(hours=47)
        todo.due_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    swept = await client.post("/api/admin/ops-todos/sweep", json={"actor": PLATFORM_ADMIN})
    assert swept.status_code == 200

    # 非合规角色不能录结论；驳回 → Guard⑥ 继续否决
    denied = await client.post(
        f"/api/law-reviews/{law_id}/decision",
        json={"approved": False, "actor": OPS},
    )
    assert denied.status_code == 403
    reject = await client.post(
        f"/api/law-reviews/{law_id}/decision",
        json={"approved": False, "conclusion": "资质不足", "actor": COMPLIANCE},
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"
    gate = (await client.get(f"/api/pws/{pws['pws_id']}/ccr/gate")).json()
    assert gate["law_review_passed"] is False

    again = await client.post(
        f"/api/law-reviews/{law_id}/decision",
        json={"approved": True, "actor": COMPLIANCE},
    )
    assert again.status_code == 409  # 已决不可改

    # 通过路径：新版本重冻后再走法审
    v2 = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze",
        json={"actor": OWNER, "reason_code": "asset_increment"},
    )
    new_pws = v2.json()["pws"]
    run3 = await client.post(f"/api/pws/{new_pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    new_law = run3.json()["law_review"]
    approve = await client.post(
        f"/api/law-reviews/{new_law['law_review_id']}/decision",
        json={"approved": True, "conclusion": "合规", "actor": COMPLIANCE},
    )
    assert approve.json()["status"] == "approved"
    gate = (await client.get(f"/api/pws/{new_pws['pws_id']}/ccr/gate")).json()
    assert gate["law_review_passed"] is True


async def test_sensitive_flag_triggers_without_domain_match(client, session_factory):
    ps_id = await _make_ps(session_factory, industry="wart_pen", sensitive=True)
    pws = await _freeze(client, ps_id, risk_control=True)
    run = await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    law = run.json()["law_review"]
    assert law is not None and law["domain"] == "wart_pen"


# ---------- Q51 词表生效即扫 ----------

async def test_q51_rescan_todo_idempotent(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id, contents=("保证有效", "水润肤感", "清爽质地"))

    wl = await client.post(
        "/api/admin/compliance-wordlist",
        json={"item": {"word": "保证", "level": "critical", "action": "ban"}, "actor": OPS},
    )
    impacted = wl.json()["q51_impacted"]
    assert len(impacted) == 1 and impacted[0]["pws_id"] == pws["pws_id"]
    todo_id = impacted[0]["todo_id"]

    async with session_factory() as session:
        todo = await session.get(OpsTodo, todo_id)
        assert todo.assignee_role == "whitelist_owner"
        assert todo.detail["reason_code"] == "wordlist_hit"

    # 再次保存（PUT）同词命中 → 复用开放待办，不重开
    entry_id = wl.json()["entry_id"]
    upd = await client.put(
        f"/api/admin/compliance-wordlist/{entry_id}",
        json={"item": {"word": "保证", "level": "critical", "action": "ban"}, "actor": OPS},
    )
    assert upd.status_code == 200
    assert upd.json()["q51_impacted"][0]["todo_id"] == todo_id

    # 不相关词不产生待办
    other = await client.post(
        "/api/admin/compliance-wordlist",
        json={"item": {"word": "外星词汇", "level": "high", "action": "ban"}, "actor": OPS},
    )
    assert other.json()["q51_impacted"] == []

    # owner 按 Q29 强制档执行重冻（wordlist_hit），新版本可再清洗
    refreeze = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze",
        json={"actor": OWNER, "reason_code": "wordlist_hit"},
    )
    assert refreeze.json()["pws"]["refreeze_tier"] == "forced"
