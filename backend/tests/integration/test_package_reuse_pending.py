"""段9 三包重配载体甲（Q264，Q45 落地）：运营待重配清单 + 人工更新清零 + PCP 触发。

覆盖：
- GET /api/admin/packages/reuse-pending：跨阈值 active 包入清单，未跨不入；
- PUT /api/packages/{id} 人工更新 payload → usage_count 清零 + package.reuse_reset 审计；
- PUT /api/pcp/{id} PCP 权重更新 → 该 PS×platform 全部 active 三包各写一条
  package.reuse_threshold_reached（trigger=pcp_update）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config_center.cache import config_cache
from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.staff_auth.deps import get_auth_session
from app.decision.layer_strategy.models import Package
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
from tests.integration.staff_tokens import bearer, issue_write_token
from tests.integration.test_fcw_api import (
    COMPLIANCE,
    OPS,
    PLATFORM,
    _freeze,
    _make_ps,
    _seed_static_inputs,
)

REUSE_THRESHOLD_KEY = "package.reuse_threshold"
PENDING_PATH = "/api/admin/packages/reuse-pending"


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
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def _reset_threshold():
    config_cache.invalidate()
    yield
    config_cache.invalidate()


def _pending_query():
    return {"actor_id": "ops-1", "roles": ["operations"]}


async def _packages(session_factory) -> dict[str, Package]:
    async with session_factory() as session:
        rows = (await session.scalars(select(Package))).all()
        return {p.kind: p for p in rows}


async def _audits(session_factory, action: str) -> list[tuple[str, dict]]:
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == action)
            )
        ).all()
        return [(r.entity_id, r.detail) for r in rows]


async def _bump_threshold(client, session_factory):
    """发证跨阈值：阈值 1 → 发一次证 → 三包 usage_count=1≥1 → 均入待重配清单。"""
    config_cache.apply({REUSE_THRESHOLD_KEY: 1}, versions={REUSE_THRESHOLD_KEY: 1})
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    resp = await client.post("/api/fcw/assemble", json={
        "product_space_id": ps_id, "platform": PLATFORM, "slot_id": slot_id,
        "goal": "ENGAGEMENT", "actor": OPS,
    })
    assert resp.status_code == 200, resp.text
    return ps_id


async def test_reuse_pending_lists_crossed_packages(client, session_factory):
    ps_id = await _bump_threshold(client, session_factory)
    resp = await client.get(PENDING_PATH, params=_pending_query())
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 3, rows  # csp/cstp/cep 三包均跨阈值
    assert all(r["usage_count"] == 1 for r in rows), rows
    assert all(r["threshold"] == 1 for r in rows), rows
    assert {r["kind"] for r in rows} == {"csp", "cstp", "cep"}, rows
    assert all(r["product_space_id"] == ps_id for r in rows), rows


async def test_reuse_pending_empty_below_threshold(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    resp = await client.post("/api/fcw/assemble", json={
        "product_space_id": ps_id, "platform": PLATFORM, "slot_id": slot_id,
        "goal": "ENGAGEMENT", "actor": OPS,
    })
    assert resp.status_code == 200, resp.text
    # 默认阈值 20：一次发证不跨 → 空清单。
    resp = await client.get(PENDING_PATH, params=_pending_query())
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_manual_update_resets_usage_count(client, session_factory):
    await _bump_threshold(client, session_factory)
    pkgs = await _packages(session_factory)
    csp = pkgs["csp"]
    # 人工更新 payload → usage_count 清零 + reuse_reset 审计。
    resp = await client.put(
        f"/api/packages/{csp.package_id}",
        json={
            "payload": {"goal": "种草", "stage": "认知", "angle": "成分",
                        "intensity": "强", "cta": "硬", "emotion": "振奋"},
            "conf": 0.8, "actor": OPS,
        },
    )
    assert resp.status_code == 200, resp.text
    pkgs = await _packages(session_factory)
    assert pkgs["csp"].usage_count == 0, pkgs["csp"].usage_count
    # 其他两包不受影响（仍跨阈值在清单）。
    assert pkgs["cstp"].usage_count == 1
    assert pkgs["cep"].usage_count == 1
    resets = await _audits(session_factory, "package.reuse_reset")
    assert len(resets) == 1, resets
    assert resets[0][1]["kind"] == "csp"
    # 清单只剩两包。
    resp = await client.get(PENDING_PATH, params=_pending_query())
    assert {r["kind"] for r in resp.json()} == {"cstp", "cep"}


async def test_pcp_update_triggers_reuse_audit_on_all_active_packages(client, session_factory):
    ps_id = await _make_ps(session_factory)
    await _seed_static_inputs(client, ps_id)  # 建 PCP + 三包
    # 拿到 PCP id。
    pcp_list = await client.get(f"/api/product-spaces/{ps_id}/pcp")
    pcp_id = pcp_list.json()[0]["pcp_id"]
    # PCP 更新：复用模板 weights（17 键 Σ=1）。
    weights = PCP_TEMPLATE_SEEDS[0]["weights"]
    resp = await client.put(
        f"/api/pcp/{pcp_id}",
        json={"weights": weights, "actor": OPS},
    )
    assert resp.status_code == 200, resp.text
    audits = await _audits(session_factory, "package.reuse_threshold_reached")
    assert len(audits) == 3, audits  # 三包各一条
    assert all(a[1]["trigger"] == "pcp_update" for a in audits), audits
    assert all(a[1]["pcp_id"] == pcp_id for a in audits), audits
    assert {a[1]["kind"] for a in audits} == {"csp", "cstp", "cep"}, audits
    assert all(a[1]["threshold"] == 20 for a in audits), audits


async def test_pcp_update_only_targets_same_ps_platform(client, session_factory):
    ps_id = await _make_ps(session_factory)
    await _seed_static_inputs(client, ps_id)  # PS1 三包 + PCP
    # PS2：只建三包（不建 slot/PCP，避免 slot code 冲突）——验证 PCP 更新不跨 PS 触发。
    ps2 = await _make_ps(session_factory, tenant="t2")
    payloads = {
        "csp": {"goal": "种草", "stage": "认知", "angle": "成分",
                "intensity": "中", "cta": "软", "emotion": "安心"},
        "cstp": {"struct": "钩子-论点-收尾"},
        "cep": {"tone": "温和", "perspective": "第二人称",
                "explicit": "低", "soften": "轻"},
    }
    for kind, payload in payloads.items():
        resp = await client.post(
            f"/api/product-spaces/{ps2}/packages",
            json={"item": {
                "kind": kind, "platform": PLATFORM, "goal": "ENGAGEMENT",
                "payload": payload, "conf": 0.8,
            }, "actor": OPS},
        )
        assert resp.status_code == 201, resp.text
    pcp_list = await client.get(f"/api/product-spaces/{ps_id}/pcp")
    pcp_id = pcp_list.json()[0]["pcp_id"]
    weights = PCP_TEMPLATE_SEEDS[0]["weights"]
    resp = await client.put(
        f"/api/pcp/{pcp_id}",
        json={"weights": weights, "actor": OPS},
    )
    assert resp.status_code == 200, resp.text
    audits = await _audits(session_factory, "package.reuse_threshold_reached")
    # 只有 PS1 的三包收到触发审计（PCP 属 PS1）；PS2 的三包不受影响。
    assert len(audits) == 3, audits
    async with session_factory() as session:
        ps2_pkg_ids = {
            p.package_id
            for p in (await session.scalars(select(Package).where(
                Package.product_space_id == ps2
            ))).all()
        }
    assert all(a[0] not in ps2_pkg_ids for a in audits), audits
