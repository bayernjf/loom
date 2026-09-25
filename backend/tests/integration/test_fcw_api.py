"""段11 FCW 组装 API 集成测试（08 M8 验收行）。

覆盖：E1.1 唯一出口 7 Guard 全绿才发 final_id（Q52/Q53）、
Q54 分仅排序、Q55 任务驱动批量+逐项失败留痕+审计、
重复发证 409、旧版 PWS Guard⑦ 拦截、法审 Guard⑥ 联动。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.main import app
from app.platform.platform_adaptation.models import GoalFitWeight, PcpTemplate
from app.platform.platform_adaptation.seeds import (
    FIT_WEIGHT_SEEDS,
    PCP_TEMPLATE_SEEDS,
)
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.fieldpool.models import FPSourceRoute
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

PLATFORM = "x_platform"
GOAL = "ENGAGEMENT"


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
            [G2Field(fid="f_a", cat="common", field_name="字段A"),
             G2Field(fid="f_b", cat="selling", field_name="字段B"),
             FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
             FPSourceRoute(route="compliance_risk", name="合规风险面", sort_order=2)]
            + [ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS]
        )
        for seed in FIT_WEIGHT_SEEDS:
            session.add(GoalFitWeight(goal=seed["goal"], weights=seed["weights"]))
        for tpl in PCP_TEMPLATE_SEEDS:
            session.add(
                PcpTemplate(
                    template_id=tpl["template_id"],
                    code=tpl["code"],
                    name=tpl["name"],
                    weights=tpl["weights"],
                )
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


async def _freeze(client, ps_id, contents=("温和洁面", "水润肤感", "清爽质地")):
    dims = [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)]
    pool = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools",
        json={"dimensions": dims, "actor": OPS},
    )
    assert pool.status_code == 200, pool.text
    pool_id = pool.json()["pool_id"]
    await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    cur = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    dim_ids = [d["dimension_id"] for d in cur.json()["dimensions"]]
    items = [
        {"content": c, "dimension_id": dim_ids[i], "ai_risk": "low", "evidence": "语料"}
        for i, c in enumerate(contents)
    ]
    batch = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches", json={"items": items, "actor": OPS}
    )
    for c in batch.json()["candidates"]:
        await client.post(
            f"/api/atom-candidates/{c['candidate_id']}/approve", json={"actor": REVIEWER}
        )
    atoms = (await client.get(f"/api/product-spaces/{ps_id}/atoms")).json()
    atom_ids = [a["atom_id"] for a in atoms]
    funnel = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/funnel",
        json={
            "combos": [{
                "atom_ids": atom_ids[:2],
                "logic_score": 0.8,
                "fit_score": 0.6,
                "goals": [GOAL],
            }],
            "actor": OPS,
        },
    )
    assert funnel.status_code == 200, funnel.text
    pwc_id = funnel.json()[0]["pwc_id"]
    await client.post(f"/api/pwcs/{pwc_id}/gate", json={"decision": "approve", "actor": REVIEWER})
    freeze = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
    )
    assert freeze.status_code == 200, freeze.text
    return freeze.json()["pws"]


async def _seed_static_inputs(client, ps_id):
    slot = await client.post(
        "/api/admin/publish-slots",
        json={"item": {
            "platform": PLATFORM, "code": "xs-01", "name": "短视频位",
            "slot_type": "short_video",
            "traffic": 70, "safe": 80, "conv": 60, "load": 50,
        }, "actor": OPS},
    )
    assert slot.status_code == 201, slot.text
    slot_id = slot.json()["slot_id"]

    pcp = await client.post(
        f"/api/product-spaces/{ps_id}/pcp",
        json={"platform": PLATFORM, "template_code": "short_video", "actor": OPS},
    )
    assert pcp.status_code == 201, pcp.text

    payloads = {
        "csp": {"goal": "种草", "stage": "认知", "angle": "成分",
                "intensity": "中", "cta": "软", "emotion": "安心"},
        "cstp": {"struct": "钩子-论点-收尾"},
        "cep": {"tone": "温和", "perspective": "第二人称",
                "explicit": "低", "soften": "轻"},
    }
    for kind, payload in payloads.items():
        resp = await client.post(
            f"/api/product-spaces/{ps_id}/packages",
            json={"item": {
                "kind": kind, "platform": PLATFORM, "goal": GOAL,
                "payload": payload, "conf": 0.8,
            }, "actor": OPS},
        )
        assert resp.status_code == 201, resp.text
    return slot_id


def _assemble_body(ps_id, slot_id, **kw):
    return {
        "product_space_id": ps_id,
        "platform": PLATFORM,
        "slot_id": slot_id,
        "goal": GOAL,
        "actor": OPS,
        **kw,
    }


# ---------- 全绿发证（E1.1 唯一出口） ----------

async def test_assemble_green_path_mints_final_id_with_audit(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)

    # 未清洗 → Guard② 不放行（无报告不等于放行）
    blocked = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert blocked.status_code == 409
    failed_guards = {g["code"]: g["passed"] for g in blocked.json()["detail"]["guards"]}
    assert failed_guards["g2_compliance_clear"] is False

    run = await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    assert run.json()["report"]["status"] == "clean"

    resp = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert resp.status_code == 200, resp.text
    fcw = resp.json()
    assert fcw["publish_status"] == "published"
    assert fcw["guards_passed"] is True
    assert fcw["pws_id"] == pws["pws_id"]
    assert fcw["ccr_report_id"]
    # Q54：pwc 0.82×100×0.4 + fit 66×0.3 + conf 0.8×100×0.3 = 76.6（仅排序）
    assert fcw["score"] is not None
    assert abs(fcw["score"] - 76.6) < 1e-6
    assert fcw["score_incomplete"] is False

    listed = await client.get(f"/api/product-spaces/{ps_id}/fcw")
    assert [r["final_id"] for r in listed.json()] == [fcw["final_id"]]
    got = await client.get(f"/api/fcw/{fcw['final_id']}")
    assert got.status_code == 200

    async with session_factory() as session:
        logs = (
            await session.scalars(
                select(AuditLog).where(AuditLog.entity_id == fcw["final_id"])
            )
        ).all()
        actions = {log.action for log in logs}
        assert "fcw.issued" in actions
        detail = next(log.detail for log in logs if log.action == "fcw.issued")
        assert detail["E1_owner"] == "publishFCW"
        assert set(detail["materials"]) >= {
            "pws_id", "pwc_id", "pcp_id", "csp_package_id",
            "cstp_package_id", "cep_package_id", "ccr_report_id",
        }
        # 阻断尝试也留审计（Q55：发证必审计，失败亦留痕）
        blocked_logs = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "fcw.assembly_blocked")
            )
        ).all()
        assert len(blocked_logs) == 1


async def test_role_and_input_errors(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})

    body = _assemble_body(ps_id, slot_id)
    denied = await client.post(
        "/api/fcw/assemble", json={**body, "actor": NOBODY}
    )
    assert denied.status_code == 403

    bad_goal = await client.post(
        "/api/fcw/assemble", json={**body, "goal": "NOPE"}
    )
    assert bad_goal.status_code == 404

    missing = await client.post(
        "/api/fcw/assemble", json={**body, "slot_id": "nonexistent"}
    )
    assert missing.status_code == 404

    # 无 active PWS 的 PS
    ps2 = await _make_ps(session_factory)
    no_pws = await client.post(
        "/api/fcw/assemble", json=_assemble_body(ps2, slot_id)
    )
    assert no_pws.status_code == 404


async def test_missing_packages_blocks_without_final_id(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    # 只建 slot，不建 PCP/三包
    slot = await client.post(
        "/api/admin/publish-slots",
        json={"item": {
            "platform": PLATFORM, "code": "xs-02", "name": "位2",
            "slot_type": "short_video",
        }, "actor": OPS},
    )
    slot_id = slot.json()["slot_id"]
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})

    resp = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert resp.status_code == 409
    assert "materials missing" in resp.json()["detail"]
    listed = await client.get(f"/api/product-spaces/{ps_id}/fcw")
    assert listed.json() == []


async def test_duplicate_and_superseded_pws_guards(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})

    first = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert first.status_code == 200
    dup = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert dup.status_code == 409 and "already issued" in dup.json()["detail"]

    # Q29 重冻：旧版 superseded/is_active=false → 指定旧 pws_id 过 Guard①⑦ 失败
    v2 = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze",
        json={"actor": OWNER, "reason_code": "asset_increment"},
    )
    assert v2.status_code == 200
    old = await client.post(
        "/api/fcw/assemble", json=_assemble_body(ps_id, slot_id, pws_id=pws["pws_id"])
    )
    assert old.status_code == 409
    codes = {g["code"]: g["passed"] for g in old.json()["detail"]["guards"]}
    assert codes["g1_pws_frozen"] is False
    assert codes["g7_pws_active_version"] is False


async def test_q55_task_driven_batch_with_per_item_failures(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot1 = await _seed_static_inputs(client, ps_id)
    slot2_resp = await client.post(
        "/api/admin/publish-slots",
        json={"item": {
            "platform": PLATFORM, "code": "xs-03", "name": "位3",
            "slot_type": "short_video",
            "traffic": 50, "safe": 50, "conv": 50, "load": 50,
        }, "actor": OPS},
    )
    slot2 = slot2_resp.json()["slot_id"]
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})

    # 未给 slot_ids：系统从平台 active 发布位自动配料
    task = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 2, "actor": OPS,
        },
    )
    assert task.status_code == 201, task.text
    body = task.json()
    assert body["status"] == "completed"
    assert body["results"]["requested"] == 2
    assert len(body["results"]["issued"]) == 2
    assert body["results"]["failures"] == []
    task_id = body["task_id"]

    got = await client.get(f"/api/fcw/assembly-tasks/{task_id}")
    assert got.status_code == 200
    issued_ids = {r["final_id"] for r in body["results"]["issued"]}
    listed = await client.get(f"/api/product-spaces/{ps_id}/fcw")
    assert {r["final_id"] for r in listed.json()} == issued_ids
    assert all(r["task_id"] == task_id for r in listed.json())

    # 再发同样 2 个发布位：逐条去重失败不阻断任务，失败全留痕
    rerun = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 2, "slot_ids": [slot1, slot2], "actor": OPS,
        },
    )
    assert rerun.status_code == 201
    rb = rerun.json()
    assert rb["results"]["issued"] == []
    assert len(rb["results"]["failures"]) == 2

    # count 与 slot_ids 数不一致 422；越权 403
    bad = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 1, "slot_ids": [slot1, slot2], "actor": OPS,
        },
    )
    assert bad.status_code == 422
    denied = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 1, "slot_ids": [slot1], "actor": NOBODY,
        },
    )
    assert denied.status_code == 403


async def test_law_review_blocks_g6_until_approved(client, session_factory):
    await client.post(
        "/api/admin/cp-law-domains",
        json={"item": {"code": "medical", "name": "医疗健康"}, "actor": COMPLIANCE},
    )
    ps_id = await _make_ps(session_factory, industry="medical")
    dims = [
        _dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3),
        _dim(4, role="risk_control", fid=None),
    ]
    pool = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools",
        json={"dimensions": dims, "actor": OPS},
    )
    pool_id = pool.json()["pool_id"]
    await client.post(
        f"/api/field-pools/{pool_id}/gate", json={"decision": "approve", "actor": REVIEWER}
    )
    cur = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    dim_ids = [d["dimension_id"] for d in cur.json()["dimensions"]]
    items = [
        {"content": c, "dimension_id": dim_ids[i], "ai_risk": "low", "evidence": "语料"}
        for i, c in enumerate(("温和护理", "水润肤感", "清爽质地"))
    ]
    batch = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches", json={"items": items, "actor": OPS}
    )
    for c in batch.json()["candidates"]:
        await client.post(
            f"/api/atom-candidates/{c['candidate_id']}/approve", json={"actor": REVIEWER}
        )
    atoms = (await client.get(f"/api/product-spaces/{ps_id}/atoms")).json()
    funnel = await client.post(
        f"/api/product-spaces/{ps_id}/pwc/funnel",
        json={"combos": [{
            "atom_ids": [a["atom_id"] for a in atoms[:2]],
            "logic_score": 0.8, "fit_score": 0.6, "goals": [GOAL],
        }], "actor": OPS},
    )
    pwc_id = funnel.json()[0]["pwc_id"]
    await client.post(f"/api/pwcs/{pwc_id}/gate", json={"decision": "approve", "actor": REVIEWER})
    freeze = await client.post(
        f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
    )
    pws = freeze.json()["pws"]
    slot_id = await _seed_static_inputs(client, ps_id)
    run = await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    law_id = run.json()["law_review"]["law_review_id"]

    blocked = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert blocked.status_code == 409
    codes = {g["code"]: g["passed"] for g in blocked.json()["detail"]["guards"]}
    assert codes["g6_law_review"] is False
    assert codes["g2_compliance_clear"] is True  # 清洗本身干净

    await client.post(
        f"/api/law-reviews/{law_id}/decision",
        json={"approved": True, "conclusion": "合规", "actor": COMPLIANCE},
    )
    ok = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert ok.status_code == 200, ok.text


# ---------- Q200 #34：治理不变式运行期强制 ----------

async def test_assemble_gated_without_token_is_401(client, session_factory, monkeypatch):
    """门控开启时自报 operations 不再能直接 mint final_id（Q199 探针：修复前 200）。

    修复前 service._require_ops 只查自报 roles、不经 rbac.require_any_role——"唯一
    出口"只是注释约定；本条即判红哨兵：门控开 + 无 staff 令牌 → 401。
    """
    from app.core.db import settings

    monkeypatch.setattr(settings, "staff_auth_enabled", True)
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})

    resp = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert resp.status_code == 401, resp.text

    # 任务写口同闸：门控开 + 无令牌 → 401（不是 200/201 异步入队）。
    task = await client.post(
        "/api/fcw/assembly-tasks",
        json={**_assemble_body(ps_id, slot_id), "count": 1},
    )
    assert task.status_code == 401, task.text


async def test_assemble_gate_off_self_declared_operations_still_ok(
    client, session_factory
):
    """门控关（V1 默认）维持自报口径：正文口照常发证（Q178 纯加法承诺）。

    与上一条成对：401 只来自「门控开启缺认证」，不破坏 V1 默认部署路径。
    """
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    resp = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert resp.status_code == 200, resp.text
