"""段7/8/9 静态底表 API 集成测试（08 M11 验收：Q34/Q35/Q36/Q40/Q45/Q52）。"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from app.platform.platform_adaptation.pa_rules import WEIGHT_KEYS_17
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.product_intake.models import ProductIntakeApplication, ProductSpace

OPS = {"id": "ops-1", "roles": ["operations"]}
NOBODY = {"id": "nobody-1", "roles": []}

SLOT = {
    "platform": "x_platform",
    "code": "X-01",
    "name": "X 平台主发布位",
    "slot_type": "main",
    "chars_max": 280,
    "traffic": 80,
    "safe": 50,
    "conv": 40,
    "load": 100,
    "source_url": "https://example.com/rules",
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
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    from app.platform.platform_adaptation.models import GoalFitWeight, PcpTemplate
    from app.platform.platform_adaptation.seeds import (
        FIT_WEIGHT_SEEDS,
        PCP_TEMPLATE_SEEDS,
    )

    async with session_factory() as session:
        session.add_all([ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS])
        session.add_all(
            [GoalFitWeight(goal=row["goal"], weights=row["weights"]) for row in FIT_WEIGHT_SEEDS]
        )
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


# ---------- 发布位档案（Q35） ----------

async def test_slot_crud_role_code_and_fit_score(client):
    forbidden = await client.post(
        "/api/admin/publish-slots", json={"item": SLOT, "actor": NOBODY}
    )
    assert forbidden.status_code == 403

    resp = await client.post(
        "/api/admin/publish-slots", json={"item": SLOT, "actor": OPS}
    )
    assert resp.status_code == 201, resp.text
    slot = resp.json()
    assert slot["score_source"] == "manual_eval"  # 主观字段明示人工评估
    assert slot["source_url"] == "https://example.com/rules"

    dup = await client.post("/api/admin/publish-slots", json={"item": SLOT, "actor": OPS})
    assert dup.status_code == 409

    # Q34：ENGAGEMENT 种子权重 0.4/0.2/0.2/0.2 → 32+10+8+20=70
    fit = await client.get(
        f"/api/admin/publish-slots/{slot['slot_id']}/fit-score?goal=ENGAGEMENT"
    )
    assert fit.status_code == 200
    body = fit.json()
    assert body["incomplete"] is False
    assert body["fit_score"] == 70

    # 原文未给权重的目的 → 不凑分
    missing = await client.get(
        f"/api/admin/publish-slots/{slot['slot_id']}/fit-score?goal=TRUST"
    )
    assert missing.json()["incomplete"] is True
    assert missing.json()["fit_score"] is None

    archived = await client.request(
        "DELETE",
        f"/api/admin/publish-slots/{slot['slot_id']}",
        json={"actor": OPS},
    )
    assert archived.status_code == 204
    gone = await client.get("/api/admin/publish-slots")
    assert gone.json() == []


# ---------- Q34 权重矩阵 ----------

async def test_fit_weights_validation(client):
    bad = await client.put(
        "/api/admin/fit-weights",
        json={"goal": "TRUST", "weights": {"traffic": 0.5, "safe": 0.5, "conv": 0.0, "load": 0.2}, "actor": OPS},
    )
    assert bad.status_code == 422
    assert "weight_sum_not_1" in bad.json()["detail"]["violations"]

    unknown_goal = await client.put(
        "/api/admin/fit-weights",
        json={"goal": "NOPE", "weights": {"traffic": 0.25, "safe": 0.25, "conv": 0.25, "load": 0.25}, "actor": OPS},
    )
    assert unknown_goal.status_code == 404

    ok = await client.put(
        "/api/admin/fit-weights",
        json={"goal": "TRUST", "weights": {"traffic": 0.25, "safe": 0.25, "conv": 0.25, "load": 0.25}, "actor": OPS},
    )
    assert ok.status_code == 200, ok.text
    rows = await client.get("/api/admin/fit-weights")
    goals = {r["goal"] for r in rows.json()}
    assert {"ENGAGEMENT", "CONVERSION", "TRUST"} <= goals


# ---------- 平台规则（Q36） ----------

async def test_rule_conflict_overwrite_and_match(client):
    item = {
        "selector_level": "platform",
        "platform": "x_platform",
        "effect": "blocked",
        "note": "R-001",
    }
    r1 = await client.post("/api/admin/platform-rules", json={"item": item, "actor": OPS})
    assert r1.status_code == 201, r1.text

    # slot 级缺 slot_id → 422
    bad_level = await client.post(
        "/api/admin/platform-rules",
        json={
            "item": {"selector_level": "slot", "platform": "x_platform", "effect": "partial"},
            "actor": OPS,
        },
    )
    assert bad_level.status_code == 422
    assert "slot_id_required" in bad_level.json()["detail"]["violations"]

    # 同层级同条件不同结论 → 409 冲突提示
    conflict = await client.post(
        "/api/admin/platform-rules",
        json={"item": {**item, "effect": "partial"}, "actor": OPS},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["conflicts"][0]["rule_id"] == r1.json()["rule_id"]

    # overwrite=true 覆盖旧规则
    overwrite = await client.post(
        "/api/admin/platform-rules",
        json={"item": {**item, "effect": "partial"}, "overwrite": True, "actor": OPS},
    )
    assert overwrite.status_code == 201
    active = await client.get("/api/admin/platform-rules")
    effects = [r["effect"] for r in active.json()]
    assert effects == ["partial"]

    # slotId 级 blocked 高于 platform 级 partial → match 取高优先级
    slot_rule = {
        "selector_level": "slot",
        "platform": "x_platform",
        "slot_id": "slot-1",
        "effect": "blocked",
    }
    r_slot = await client.post(
        "/api/admin/platform-rules", json={"item": slot_rule, "actor": OPS}
    )
    assert r_slot.status_code == 201
    match = await client.get(
        "/api/admin/platform-rules/match?platform=x_platform&slot_type=main&slot_id=slot-1"
    )
    assert match.json()["effect"] == "blocked"
    other = await client.get(
        "/api/admin/platform-rules/match?platform=x_platform&slot_type=main&slot_id=other-slot"
    )
    assert other.json()["effect"] == "partial"


# ---------- slotType 默认值 ----------

async def test_slot_type_defaults(client):
    bad = await client.put(
        "/api/admin/slot-type-defaults",
        json={"slot_type": "video", "daily_limit_min": 5, "daily_limit_max": 1, "actor": OPS},
    )
    assert bad.status_code == 422
    ok = await client.put(
        "/api/admin/slot-type-defaults",
        json={"slot_type": "video", "daily_limit_min": 1, "daily_limit_max": 3, "actor": OPS},
    )
    assert ok.status_code == 200
    rows = await client.get("/api/admin/slot-type-defaults")
    assert rows.json()[0]["daily_limit_max"] == 3


# ---------- 段8 PCP（Q39/Q40/Q52） ----------

async def test_pcp_templates_seed_and_ps_instances(session_factory, client):
    ps_id, _ = await _make_ps(session_factory)

    templates = await client.get("/api/admin/pcp-templates")
    assert templates.status_code == 200
    codes = {t["code"] for t in templates.json()}
    assert codes == {"short_video", "community", "photo_text", "ecommerce"}
    for t in templates.json():
        assert abs(sum(t["weights"].values()) - 1.0) < 1e-9
        assert set(t["weights"]) <= set(WEIGHT_KEYS_17)

    # 从模板派生
    created = await client.post(
        f"/api/product-spaces/{ps_id}/pcp",
        json={"platform": "x_platform", "template_code": "short_video", "actor": OPS},
    )
    assert created.status_code == 201, created.text
    pcp = created.json()
    assert pcp["product_space_id"] == ps_id  # Q52 配置实例归属
    assert pcp["tenant_id"] == "t1"

    # 同产品同平台仅一条 active
    dup = await client.post(
        f"/api/product-spaces/{ps_id}/pcp",
        json={"platform": "x_platform", "template_code": "ecommerce", "actor": OPS},
    )
    assert dup.status_code == 409

    # Q40：显式权重 Σ>1 → 422
    other = await client.post(
        f"/api/product-spaces/{ps_id}/pcp",
        json={"platform": "y_platform", "weights": {"goal": 0.9, "hook": 0.9}, "actor": OPS},
    )
    assert other.status_code == 422
    assert "weight_sum_exceeds_1" in other.json()["detail"]["violations"]

    # 人工直接编辑通道（Q42）
    updated = await client.put(
        f"/api/pcp/{pcp['pcp_id']}",
        json={"weights": {"goal": 0.3, "hook": 0.3}, "actor": OPS},
    )
    assert updated.status_code == 200
    assert updated.json()["template_code"] is None

    listed = await client.get(f"/api/product-spaces/{ps_id}/pcp")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    missing_ps = await client.post(
        "/api/product-spaces/ps-nope/pcp",
        json={"platform": "z", "template_code": "short_video", "actor": OPS},
    )
    assert missing_ps.status_code == 404


# ---------- 段9 三包配置实例（Q45/Q52） ----------

async def test_packages_triple_unique_and_payload_validation(session_factory, client):
    ps_id, _ = await _make_ps(session_factory)
    csp = {
        "kind": "csp",
        "platform": "x_platform",
        "goal": "ENGAGEMENT",
        "payload": {
            "goal": "种草",
            "stage": "认知",
            "angle": "成分",
            "intensity": "中",
            "cta": "软",
            "emotion": "安心",
        },
    }
    created = await client.post(
        f"/api/product-spaces/{ps_id}/packages", json={"item": csp, "actor": OPS}
    )
    assert created.status_code == 201, created.text
    package = created.json()
    assert package["tenant_id"] == "t1"  # Q52
    assert package["product_space_id"] == ps_id

    # Q45 三元组（+包型）唯一
    dup = await client.post(
        f"/api/product-spaces/{ps_id}/packages", json={"item": csp, "actor": OPS}
    )
    assert dup.status_code == 409

    # payload 缺键 422
    bad_payload = {**csp, "payload": {"goal": "种草"}}
    bad = await client.post(
        f"/api/product-spaces/{ps_id}/packages", json={"item": bad_payload, "actor": OPS}
    )
    assert bad.status_code == 422
    violations = bad.json()["detail"]["violations"]
    assert any("missing_payload_keys" in v for v in violations)

    # 未知包型 422；未知 goal 404；越权 403
    bad_kind = await client.post(
        f"/api/product-spaces/{ps_id}/packages",
        json={"item": {**csp, "kind": "nope"}, "actor": OPS},
    )
    assert bad_kind.status_code == 422
    bad_goal = await client.post(
        f"/api/product-spaces/{ps_id}/packages",
        json={"item": {**csp, "goal": "NOPE"}, "actor": OPS},
    )
    assert bad_goal.status_code == 404
    forbidden = await client.post(
        f"/api/product-spaces/{ps_id}/packages", json={"item": csp, "actor": NOBODY}
    )
    assert forbidden.status_code == 403

    # 更新与软归档
    updated = await client.put(
        f"/api/packages/{package['package_id']}",
        json={"payload": {**csp["payload"], "stage": "兴趣"}, "actor": OPS},
    )
    assert updated.status_code == 200
    archived = await client.request(
        "DELETE", f"/api/packages/{package['package_id']}", json={"actor": OPS}
    )
    assert archived.status_code == 204
    rows = await client.get(f"/api/product-spaces/{ps_id}/packages")
    assert rows.json() == []
