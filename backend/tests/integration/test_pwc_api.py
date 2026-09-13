"""段5 PWC（WF-04 确定性切片）API 集成测试。

覆盖 docs/08 M5 验收行：Q21 漏斗限量、Q22/Q22a/Q22b 评分（AI 失败不凑分）、
Q23 重合标重、Q24 取用去重/冷却/全平台用尽、Q25 contentGoals 字典、
Q26 手拼不豁免合规、Q27 库容、Q71 按分排序消费与 restock 信号。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from app.product.condition import pwc_rules
from app.product.condition import service as pwc_service
from app.product.condition.models import ContentGoal
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import (
    G2Field,
    ProductIntakeApplication,
    ProductSpace,
)

REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
OPS = {"id": "ops-1", "roles": ["operations"]}
DICT_ADMIN = {"id": "dict-1", "roles": ["dictionary_admin"]}
SYSTEM = {"id": "sys-1", "roles": ["system_api"]}
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


async def _make_ps(session_factory, *, industry="general", tenant="t1"):
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
            profile_snapshot={"f_a": "x"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


async def _approved_pool(client, ps_id):
    body = {
        "dimensions": [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)],
        "actor": OPS,
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


async def _approved_atoms(client, ps_id, contents=("温和洁面", "水润肤感"), dims=2):
    pool = await _approved_pool(client, ps_id)
    dim_ids = [d["dimension_id"] for d in pool["dimensions"][:dims]]
    items = [
        {
            "content": contents[i],
            "dimension_id": dim_ids[i],
            "ai_risk": "low",
            "evidence": "客服语料",
        }
        for i in range(len(contents))
    ]
    resp = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches", json={"items": items, "actor": OPS}
    )
    assert resp.status_code == 200, resp.text
    cids = [c["candidate_id"] for c in resp.json()["candidates"]]
    for cid in cids:
        ok = await client.post(
            f"/api/atom-candidates/{cid}/approve", json={"actor": REVIEWER}
        )
        assert ok.status_code == 200, ok.text
    atoms = await client.get(f"/api/product-spaces/{ps_id}/atoms")
    by_dim = {a["dimension_id"]: a["atom_id"] for a in atoms.json()}
    return [by_dim[d] for d in dim_ids[: len(contents)]]


def _combo(atom_ids, **kw):
    base = {"atom_ids": atom_ids, "logic_score": 0.8, "fit_score": 0.6}
    base.update(kw)
    return base


async def _funnel(client, ps_id, combos, **extra):
    body = {"combos": combos, "actor": OPS, **extra}
    return await client.post(f"/api/product-spaces/{ps_id}/pwc/funnel", json=body)


async def _approve_pwc(client, pwc_id):
    return await client.post(
        f"/api/pwcs/{pwc_id}/gate", json={"decision": "approve", "actor": REVIEWER}
    )


async def _seeded_ps(client, session_factory):
    ps_id = await _make_ps(session_factory)
    atoms = await _approved_atoms(client, ps_id)
    return ps_id, atoms


# ---------- Q21 漏斗前置与结构校验 ----------

async def test_funnel_requires_ps_and_approved_pool(client, session_factory):
    ps_id = await _make_ps(session_factory)
    resp = await _funnel(client, ps_id, [_combo(["x", "y"])])
    assert resp.status_code == 409

    missing = await _funnel(client, "ps-nope", [_combo(["x", "y"])])
    assert missing.status_code == 404


async def test_funnel_structural_validation(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)

    unknown = await _funnel(client, ps_id, [_combo([atoms[0], "atom-nope"])])
    assert unknown.status_code == 422

    one_dim = await _funnel(client, ps_id, [_combo([atoms[0], atoms[0]])])
    assert one_dim.status_code == 422

    dup = await _funnel(
        client, ps_id, [_combo(atoms), _combo(list(reversed(atoms)))]
    )
    assert dup.status_code == 422

    big = await _funnel(
        client, ps_id, [_combo(atoms)] * 51, batch_size=50
    )
    assert big.status_code == 422

    bad_goal = await _funnel(
        client, ps_id, [_combo(atoms, goals=["NOPE"])]
    )
    assert bad_goal.status_code == 422


async def test_cross_tenant_atom_rejected(client, session_factory):
    ps1, atoms1 = await _seeded_ps(client, session_factory)
    ps2 = await _make_ps(session_factory, tenant="t2")
    atoms2 = await _approved_atoms(client, ps2, contents=("另一产品词", "别的词"))
    resp = await _funnel(client, ps1, [_combo([atoms1[0], atoms2[0]])])
    assert resp.status_code == 422
    assert "another product space" in resp.text


# ---------- Q22 评分 / Q22b AI 失败 ----------

async def test_funnel_scores_empty_pool(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    resp = await _funnel(client, ps_id, [_combo(atoms)])
    assert resp.status_code == 200, resp.text
    pwc = resp.json()[0]
    assert pwc["gate_status"] == "pending"
    assert pwc["status"] == "pending_gate"
    # 合理性 0.7、多样性 1.0（空池）→ 0.82
    assert round(pwc["score"], 6) == 0.82
    assert pwc["score_detail"]["diversity"] == 1.0


async def test_ai_failure_not_fabricated(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    resp = await _funnel(client, ps_id, [{"atom_ids": atoms}])
    assert resp.status_code == 200
    pwc = resp.json()[0]
    assert pwc["score"] is None
    assert pwc["score_incomplete"] is True
    # 人工 Gate 仍可放行（score 不做门槛，Q22a）
    ok = await _approve_pwc(client, pwc["pwc_id"])
    assert ok.status_code == 200
    assert ok.json()["status"] == "ready"


# ---------- Q22a 合规前置 / Q26 手拼 ----------

async def test_wordlist_ban_blocks_even_manual(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    wl = await client.post(
        "/api/admin/compliance-wordlist",
        json={"item": {"word": "温和", "level": "critical", "action": "ban"}, "actor": OPS},
    )
    assert wl.status_code == 200, wl.text

    ai = await _funnel(client, ps_id, [_combo(atoms)])
    assert ai.json()[0]["gate_status"] == "blocked"

    manual = await _funnel(client, ps_id, [_combo(atoms)], source="manual")
    pwc = manual.json()[0]
    assert pwc["gate_status"] == "blocked"  # Q26：手拼不豁免合规
    approve = await _approve_pwc(client, pwc["pwc_id"])
    assert approve.status_code == 409


async def test_wordlist_downgrade_does_not_block(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    await client.post(
        "/api/admin/compliance-wordlist",
        json={
            "item": {
                "word": "温和", "level": "high", "action": "downgrade",
                "downgrade_target": "亲肤",
            },
            "actor": OPS,
        },
    )
    resp = await _funnel(client, ps_id, [_combo(atoms)])
    pwc = resp.json()[0]
    assert pwc["gate_status"] == "pending"
    assert pwc["compliance"]["downgrade"][0]["word"] == "温和"


# ---------- Q23 疑重 ----------

async def test_duplicate_overlap_flag_backup(client, session_factory):
    ps_id, _atoms = await _seeded_ps(client, session_factory)
    # 需要第 3 个原子：再提一个批次挂第 3 维度
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    dim3 = pool.json()["dimensions"][2]["dimension_id"]
    batch = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches",
        json={"items": [{"content": "清爽感", "dimension_id": dim3, "evidence": "ev"}],
              "actor": OPS},
    )
    cid = batch.json()["candidates"][0]["candidate_id"]
    await client.post(f"/api/atom-candidates/{cid}/approve", json={"actor": REVIEWER})
    all_atoms = await client.get(f"/api/product-spaces/{ps_id}/atoms")
    atom_by_content = {a["content"]: a["atom_id"] for a in all_atoms.json()}
    a1, a2, a3 = (atom_by_content[k] for k in ("温和洁面", "水润肤感", "清爽感"))

    first = await _funnel(client, ps_id, [_combo([a1, a2])])
    p1 = first.json()[0]
    assert await _approve_pwc(client, p1["pwc_id"])

    # 与待用组合 2/3 重合 ≈ 0.67，不标重
    near = await _funnel(client, ps_id, [_combo([a1, a2, a3], logic_score=0.2, fit_score=0.2)])
    assert near.json()[0]["dup_of"] is None

    # 需要 ≥0.8：构造 5 原子组合不现实，改为服务层口径已在单测覆盖；
    # 这里验证完全重合（1.0）的新低分组合进备选。
    dup = await _funnel(
        client, ps_id, [_combo([a1, a2], logic_score=0.1, fit_score=0.1)]
    )
    p_dup = dup.json()[0]
    assert p_dup["dup_of"] == p1["pwc_id"]
    assert p_dup["is_backup"] is True
    # 人工 Gate 可改判放行备选
    ok = await _approve_pwc(client, p_dup["pwc_id"])
    assert ok.status_code == 200


# ---------- Gate / Q27 库容 ----------

async def test_gate_role_and_reject(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    pwc = (await _funnel(client, ps_id, [_combo(atoms)])).json()[0]

    forbidden = await client.post(
        f"/api/pwcs/{pwc['pwc_id']}/gate",
        json={"decision": "approve", "actor": OPS},
    )
    assert forbidden.status_code == 403

    reject = await client.post(
        f"/api/pwcs/{pwc['pwc_id']}/gate",
        json={"decision": "reject", "reason": "不合适", "actor": REVIEWER},
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "archived"
    again = await _approve_pwc(client, pwc["pwc_id"])
    assert again.status_code == 409


async def test_capacity_enforced_and_unlimited(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    cfg = await client.put(
        f"/api/product-spaces/{ps_id}/pwc-pool-config",
        json={"capacity": 1, "actor": OPS},
    )
    assert cfg.status_code == 200
    assert cfg.json()["capacity"] == 1

    p1 = (await _funnel(client, ps_id, [_combo(atoms, logic_score=0.9, fit_score=0.9)])).json()[0]
    assert (await _approve_pwc(client, p1["pwc_id"])).status_code == 200
    p2 = (await _funnel(client, ps_id, [_combo(atoms, logic_score=0.1, fit_score=0.1)])).json()[0]
    full = await _approve_pwc(client, p2["pwc_id"])
    assert full.status_code == 409 and "capacity" in full.text

    # 运营配无上限后可继续
    await client.put(
        f"/api/product-spaces/{ps_id}/pwc-pool-config",
        json={"capacity": None, "actor": OPS},
    )
    assert (await _approve_pwc(client, p2["pwc_id"])).status_code == 200

    # 非运营不可改库容
    denied = await client.put(
        f"/api/product-spaces/{ps_id}/pwc-pool-config",
        json={"capacity": 5, "actor": NOBODY},
    )
    assert denied.status_code == 403


# ---------- Q71 消费 / Q24 去重、冷却、用尽 ----------

async def test_consume_ordering_and_dedup(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    low = (await _funnel(client, ps_id, [_combo(atoms, logic_score=0.2, fit_score=0.2)])).json()[0]
    await _approve_pwc(client, low["pwc_id"])
    high = (await _funnel(client, ps_id, [_combo(atoms, logic_score=0.9, fit_score=0.9)])).json()[0]
    await _approve_pwc(client, high["pwc_id"])

    r1 = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "xhs", "account": "acc1", "slot": "X-01", "actor": SYSTEM},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["pwc"]["pwc_id"] == high["pwc_id"]

    # 同平台+账号+发布位不重复：取另一条
    r2 = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "xhs", "account": "acc1", "slot": "X-01", "actor": SYSTEM},
    )
    assert r2.json()["pwc"]["pwc_id"] == low["pwc_id"]

    r3 = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "xhs", "account": "acc1", "slot": "X-01", "actor": SYSTEM},
    )
    assert r3.status_code == 409  # 池空

    # 跨平台可复用（Q24）：同账号同发布位、不同平台可取高分
    r4 = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "douyin", "account": "acc1", "slot": "X-01", "actor": SYSTEM},
    )
    assert r4.json()["pwc"]["pwc_id"] == high["pwc_id"]


async def test_consume_goals_intersection(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    p = (await _funnel(client, ps_id, [_combo(atoms, goals=["TRUST"])])).json()[0]
    await _approve_pwc(client, p["pwc_id"])
    miss = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "xhs", "account": "a", "slot": "s", "goals": ["CONVERSION"],
              "actor": SYSTEM},
    )
    assert miss.status_code == 409
    hit = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "xhs", "account": "a", "slot": "s", "goals": ["TRUST"],
              "actor": SYSTEM},
    )
    assert hit.status_code == 200


async def test_cooldown_after_three_uses_and_recovery(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    p = (await _funnel(client, ps_id, [_combo(atoms)])).json()[0]
    await _approve_pwc(client, p["pwc_id"])
    for i in range(3):
        resp = await client.post(
            f"/api/product-spaces/{ps_id}/pwc/consume",
            json={"platform": "xhs", "account": f"acc{i}", "slot": "X-01",
                  "actor": SYSTEM},
        )
        assert resp.status_code == 200, resp.text
    state = resp.json()["platform_state"]
    assert state["state"] == "cooldown"

    # 冷却中：新账号也取不到
    blocked = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "xhs", "account": "acc9", "slot": "X-02", "actor": SYSTEM},
    )
    assert blocked.status_code == 409
    # 别的平台不受影响
    other = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "douyin", "account": "acc9", "slot": "X-02", "actor": SYSTEM},
    )
    assert other.status_code == 200

    # 14 天后 sweep 回待用，同平台可再取
    async with session_factory() as session:
        released = await pwc_service.sweep_cooldowns(
            session, datetime(2026, 9, 14, tzinfo=UTC) + timedelta(days=15)
        )
        await session.commit()
        assert released == 1
    again = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "xhs", "account": "acc9", "slot": "X-03", "actor": SYSTEM},
    )
    assert again.status_code == 200


async def test_all_target_platforms_used_terminal(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    await client.put(
        f"/api/product-spaces/{ps_id}/pwc-pool-config",
        json={"target_platforms": ["xhs", "douyin"], "actor": OPS},
    )
    p = (await _funnel(client, ps_id, [_combo(atoms)])).json()[0]
    await _approve_pwc(client, p["pwc_id"])
    for platform in ("xhs", "douyin"):
        ok = await client.post(
            f"/api/product-spaces/{ps_id}/pwc/consume",
            json={"platform": platform, "account": "a", "slot": "s", "actor": SYSTEM},
        )
        assert ok.status_code == 200
    detail = await client.get(f"/api/product-spaces/{ps_id}/pwcs")
    assert detail.json()[0]["status"] == "used"
    extra = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/consume",
        json={"platform": "wechat", "account": "a", "slot": "s", "actor": SYSTEM},
    )
    assert extra.status_code == 409


async def test_high_reuse_flag(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    await client.put(
        f"/api/product-spaces/{ps_id}/pwc-pool-config",
        json={"high_reuse_n": 2, "actor": OPS},
    )
    p = (await _funnel(client, ps_id, [_combo(atoms)])).json()[0]
    await _approve_pwc(client, p["pwc_id"])
    for platform in ("xhs", "douyin"):
        await client.post(
            f"/api/product-spaces/{ps_id}/pwc/consume",
            json={"platform": platform, "account": "a", "slot": "s", "actor": SYSTEM},
        )
    detail = await client.get(f"/api/product-spaces/{ps_id}/pwcs")
    assert detail.json()[0]["high_reuse"] is True


# ---------- Q24/Q61 爆款手工标注 / 归档 ----------

async def test_hot_mark_and_archive(client, session_factory):
    ps_id, atoms = await _seeded_ps(client, session_factory)
    p = (await _funnel(client, ps_id, [_combo(atoms)])).json()[0]
    await _approve_pwc(client, p["pwc_id"])

    denied = await client.post(
        f"/api/pwcs/{p['pwc_id']}/hot", json={"is_hot": True, "actor": NOBODY}
    )
    assert denied.status_code == 403
    hot = await client.post(
        f"/api/pwcs/{p['pwc_id']}/hot", json={"is_hot": True, "actor": OPS}
    )
    assert hot.json()["is_hot"] is True

    arch = await client.post(f"/api/pwcs/{p['pwc_id']}/archive", json={"actor": OPS})
    assert arch.status_code == 200 and arch.json()["status"] == "archived"
    again = await client.post(f"/api/pwcs/{p['pwc_id']}/archive", json={"actor": OPS})
    assert again.status_code == 409


# ---------- Q25 contentGoals 字典 ----------

async def test_content_goals_dictionary(client, session_factory):
    goals = await client.get("/api/admin/content-goals")
    assert {g["code"] for g in goals.json()} == {
        "ENGAGEMENT", "CONVERSION", "EDUCATION", "TRUST", "RETENTION",
    }

    denied = await client.put(
        "/api/admin/content-goals",
        json={"code": "TRUST", "color": "#0f0", "actor": OPS},
    )
    assert denied.status_code == 403

    bad = await client.put(
        "/api/admin/content-goals",
        json={"code": "TRUST", "ratio_min": 0.8, "ratio_max": 0.2, "actor": DICT_ADMIN},
    )
    assert bad.status_code == 422

    ok = await client.put(
        "/api/admin/content-goals",
        json={"code": "TRUST", "color": "#0f0", "ratio_min": 0.1, "ratio_max": 0.3,
              "actor": DICT_ADMIN},
    )
    assert ok.status_code == 200 and ok.json()["color"] == "#0f0"

    arch = await client.post(
        "/api/admin/content-goals/TRUST/archive", json={"actor": DICT_ADMIN}
    )
    assert arch.status_code == 200
    ps_id, atoms = await _seeded_ps(client, session_factory)
    blocked = await _funnel(client, ps_id, [_combo(atoms, goals=["TRUST"])])
    assert blocked.status_code == 422
