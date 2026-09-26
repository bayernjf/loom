"""Q155 台内白名单卡片 6 层原料包 JSON 导出集成测试（docs/09:87，02 C1.99）。

与中台 /api/exports/fcw.json（final_id-only）是两个面：本口按单条 final_id
反解析产品 PWS / 平台 PCP / 策略 CSP / 结构 CSTP / 表达 CEP / 合规 CCR 六层完整
快照。复用 test_fcw_api 的全链路发证 fixture（冻结→静态输入→CCR→组装）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from app.platform.platform_adaptation.models import GoalFitWeight, PcpTemplate
from app.platform.platform_adaptation.seeds import (
    FIT_WEIGHT_SEEDS,
    PCP_TEMPLATE_SEEDS,
)
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import G2Field
from tests.integration.staff_tokens import bearer, issue_staff_token
from tests.integration.test_fcw_api import (
    COMPLIANCE,
    GOAL,
    OPS,
    OWNER,
    REVIEWER,
    _assemble_body,
    _dim,
    _freeze,
    _make_ps,
    _seed_static_inputs,
)

PLATFORM = "x_platform"


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
    # Q203：E1.1 写口在门控关下也自行验真，走 get_auth_session 这条缝。
    app.dependency_overrides[get_auth_session] = get_test_session
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
        # Q203 #34：发证写口只认已验真令牌，本文件要发证，故默认带一枚 operations 令牌
        # （引导口径同 Q178 上线流程；细节见 tests/integration/staff_tokens.py）。
        ac.headers.update(
            bearer(await issue_staff_token(ac, ["operations"]))
        )
        yield ac


async def _prepare(client, session_factory, *, industry="general"):
    """建 PS → 冻结 PWS → 静态输入（slot/PCP/三包）→ 跑 CCR；返回备料四元组。"""

    ps_id = await _make_ps(session_factory, industry=industry)
    if industry == "medical":
        await client.post(
            "/api/admin/cp-law-domains",
            json={"item": {"code": "medical", "name": "医疗健康"}, "actor": COMPLIANCE},
        )
        dims = [
            _dim(1, fid="f_a"),
            _dim(2, fid="f_b"),
            _dim(3),
            _dim(4, role="risk_control", fid=None),
        ]
        pool = await client.post(
            f"/api/product-spaces/{ps_id}/field-pools",
            json={"dimensions": dims, "actor": OPS},
        )
        pool_id = pool.json()["pool_id"]
        await client.post(
            f"/api/field-pools/{pool_id}/gate",
            json={"decision": "approve", "actor": REVIEWER},
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
                f"/api/atom-candidates/{c['candidate_id']}/approve",
                json={"actor": REVIEWER},
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
        await client.post(
            f"/api/pwcs/{pwc_id}/gate", json={"decision": "approve", "actor": REVIEWER}
        )
        freeze = await client.post(
            f"/api/product-spaces/{ps_id}/pws/freeze", json={"actor": OWNER}
        )
        pws = freeze.json()["pws"]
    else:
        pws = await _freeze(client, ps_id)

    slot_id = await _seed_static_inputs(client, ps_id)
    run = await client.post(
        f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE}
    )
    assert run.status_code == 200, run.text
    return ps_id, pws, slot_id, run.json()


async def test_material_pack_returns_six_layers(client, session_factory):
    ps_id, pws, slot_id, _ccr = await _prepare(client, session_factory)
    issued = await client.post(
        "/api/fcw/assemble", json=_assemble_body(ps_id, slot_id)
    )
    assert issued.status_code == 200, issued.text
    fcw = issued.json()

    resp = await client.get(f"/api/fcw/{fcw['final_id']}/material.json")
    assert resp.status_code == 200, resp.text
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition and f"{fcw['final_id']}.json" in disposition
    pack = resp.json()

    assert pack["schema"] == "loom.fcw.material-pack.v1"
    assert pack["final_id"] == fcw["final_id"]
    assert pack["warnings"] == []

    layers = pack["layers"]
    assert set(layers) == {
        "product", "platform", "strategy", "structure", "expression", "compliance"
    }

    # 产品层：PWS 不可变快照（私域原子 + 骨架 PWC 标注）。
    product = layers["product"]
    assert product["pws_id"] == fcw["pws_id"] == pws["pws_id"]
    assert product["status"] == "frozen"
    assert product["skeleton_pwc_id"] == fcw["pwc_id"]
    atom_contents = {a["content"] for a in product["snapshot"]["atoms"]}
    assert atom_contents == {"温和洁面", "水润肤感", "清爽质地"}
    snapshot_pwc_ids = {p["pwc_id"] for p in product["snapshot"]["pwcs"]}
    assert fcw["pwc_id"] in snapshot_pwc_ids

    # 平台层：PCP 权重 + 发证发布位档案。
    platform = layers["platform"]
    assert platform["pcp_id"] == fcw["pcp_id"]
    assert isinstance(platform["weights"], dict) and platform["weights"]
    assert platform["slot"]["slot_id"] == fcw["slot_id"]
    assert platform["slot"]["code"] == "xs-01"
    assert platform["slot"]["slot_type"] == "short_video"

    # 策略 / 结构 / 表达三包：payload 定键齐全。
    assert layers["strategy"]["kind"] == "csp"
    assert layers["strategy"]["package_id"] == fcw["csp_package_id"]
    assert set(layers["strategy"]["payload"]) == {
        "goal", "stage", "angle", "intensity", "cta", "emotion"
    }
    assert layers["structure"]["kind"] == "cstp"
    assert layers["structure"]["package_id"] == fcw["cstp_package_id"]
    assert layers["structure"]["payload"]["struct"] == "钩子-论点-收尾"
    assert layers["expression"]["kind"] == "cep"
    assert layers["expression"]["package_id"] == fcw["cep_package_id"]
    assert layers["expression"]["payload"]["tone"] == "温和"

    # 合规层：发证时 CCR clean 报告；普通流程无法审记录为空。
    compliance = layers["compliance"]
    assert compliance["ccr_report_id"] == fcw["ccr_report_id"]
    assert compliance["report"]["status"] == "clean"
    assert compliance["report"]["block_required"] is False
    assert compliance["law_reviews"] == []

    # 发证元信息 + 评分 + Guard 留痕。
    assert pack["issued"]["product_space_id"] == ps_id
    assert pack["issued"]["platform"] == PLATFORM
    assert pack["issued"]["goal"] == GOAL
    assert abs(pack["issued"]["score"] - 76.6) < 1e-6
    guard_codes = {g["code"] for g in pack["guards"]["guards"]}
    assert guard_codes == {
        "g1_pws_frozen", "g2_compliance_clear", "g3_packages_active",
        "g4_product_space_consistent", "g5_tenant_consistent",
        "g6_law_review", "g7_pws_active_version",
    }


async def test_material_pack_includes_approved_law_review(client, session_factory):
    ps_id, _pws, slot_id, ccr = await _prepare(
        client, session_factory, industry="medical"
    )
    law_id = ccr["law_review"]["law_review_id"]

    # 法审 pending 时 G6 阻断、不发 final_id。
    blocked = await client.post(
        "/api/fcw/assemble", json=_assemble_body(ps_id, slot_id)
    )
    assert blocked.status_code == 409

    approved = await client.post(
        f"/api/law-reviews/{law_id}/decision",
        json={"approved": True, "conclusion": "合规", "actor": COMPLIANCE},
    )
    assert approved.status_code == 200

    issued = await client.post(
        "/api/fcw/assemble", json=_assemble_body(ps_id, slot_id)
    )
    assert issued.status_code == 200, issued.text
    fcw = issued.json()

    pack = (await client.get(f"/api/fcw/{fcw['final_id']}/material.json")).json()
    law_reviews = pack["layers"]["compliance"]["law_reviews"]
    assert len(law_reviews) == 1
    assert law_reviews[0]["law_review_id"] == law_id
    assert law_reviews[0]["status"] == "approved"
    assert law_reviews[0]["conclusion"] == "合规"
    assert pack["layers"]["compliance"]["report"]["status"] == "clean"


async def test_material_pack_unknown_final_id_404(client, session_factory):
    resp = await client.get("/api/fcw/nonexistent-id/material.json")
    assert resp.status_code == 404
