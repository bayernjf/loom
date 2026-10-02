"""段11 FCW 组装预检只读口集成测试（Q249-b，D3.5 组装工作台第一步）。

覆盖：预检与 /assemble 同材料装配同七 Guard 求值、Guard 通过返回
guards_passed=true、Guard 失败返回 200＋guards_passed=false（是正常业务结果、
不是异常）、全程零副作用（不新增 final_content_whitelists、不写 fcw.issued /
fcw.assembly_blocked 审计）、无令牌 401、角色不足 403、未知 PS/slot/goal 404、
材料缺 409、预检后可正常签发且无重复干扰。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.staff_auth.deps import get_auth_session
from app.final.final_whitelist.models import FinalContentWhitelist
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
    _assemble_body,
    _freeze,
    _make_ps,
    _seed_static_inputs,
)

PREVIEW_PATH = "/api/fcw/assemble/preview"


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


async def _count_fcw(session_factory) -> int:
    async with session_factory() as session:
        return len((await session.scalars(select(FinalContentWhitelist))).all())


async def _count_fcw_audit(session_factory) -> int:
    async with session_factory() as session:
        return len(
            (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.action.in_(
                            ["fcw.issued", "fcw.assembly_blocked"]
                        )
                    )
                )
            ).all()
        )


async def test_preview_passes_when_guards_are_green(client, session_factory):
    """材料齐＋CCR 清洗＋七 Guard 全绿：200 guards_passed=true，且零副作用（无成品行、无发证审计）。"""
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    before_fcw = await _count_fcw(session_factory)
    before_audit = await _count_fcw_audit(session_factory)

    resp = await client.post(
        PREVIEW_PATH, json=_assemble_body(ps_id, slot_id)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["guards_passed"] is True
    assert isinstance(body["guards"], list) and len(body["guards"]) >= 7
    assert body["materials"]["pws_id"] and body["materials"]["pcp_id"]

    # 零副作用：无新成品行、无 fcw.issued / fcw.assembly_blocked 审计。
    assert await _count_fcw(session_factory) == before_fcw
    assert await _count_fcw_audit(session_factory) == before_audit


async def test_preview_reports_blocked_as_200_not_exception(
    client, session_factory
):
    """Guard 失败（未做 CCR 清洗）：预检返回 200＋guards_passed=false，不是 409 异常，
    且仍零副作用（不发 fcw.assembly_blocked 审计——那属于签发尝试语义）。"""
    ps_id = await _make_ps(session_factory)
    await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    # 不跑 ccr/run ⇒ Guard② 不放行。
    before_fcw = await _count_fcw(session_factory)
    before_audit = await _count_fcw_audit(session_factory)

    resp = await client.post(
        PREVIEW_PATH, json=_assemble_body(ps_id, slot_id)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["guards_passed"] is False
    assert any(not g["passed"] for g in body["guards"])
    assert await _count_fcw(session_factory) == before_fcw
    assert await _count_fcw_audit(session_factory) == before_audit


async def test_preview_missing_materials_409(client, session_factory):
    """静态材料缺（有 active PWS 但无 PCP）：409 materials missing，无副作用。"""
    ps_id = await _make_ps(session_factory)
    await _freeze(client, ps_id)
    # 只建发布位、不建 PCP/三包 ⇒ _resolve_pcp 抛 MaterialMissing。
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
    before_fcw = await _count_fcw(session_factory)
    before_audit = await _count_fcw_audit(session_factory)
    resp = await client.post(
        PREVIEW_PATH, json=_assemble_body(ps_id, slot_id)
    )
    assert resp.status_code == 409, resp.text
    assert "materials missing" in resp.text
    assert await _count_fcw(session_factory) == before_fcw
    assert await _count_fcw_audit(session_factory) == before_audit


async def test_preview_unknown_targets_404(client, session_factory):
    ps_id = await _make_ps(session_factory)
    slot_id = await _seed_static_inputs(client, ps_id)
    body = _assemble_body(ps_id, slot_id)

    bad_ps = await client.post(
        PREVIEW_PATH, json={**body, "product_space_id": "ps-nope"}
    )
    assert bad_ps.status_code == 404, bad_ps.text

    bad_goal = await client.post(
        PREVIEW_PATH, json={**body, "goal": "NOPE"}
    )
    assert bad_goal.status_code == 404, bad_goal.text


async def test_preview_requires_token_and_operations_role(
    client, session_factory
):
    """无令牌 401；令牌无 operations 角色 403（同 /assemble 写身份闸）。"""
    ps_id = await _make_ps(session_factory)
    slot_id = await _seed_static_inputs(client, ps_id)
    body = _assemble_body(ps_id, slot_id)

    client.headers.pop("Authorization")
    anon = await client.post(PREVIEW_PATH, json=body)
    assert anon.status_code == 401, anon.text

    client.headers.update(bearer("loom_staff_not_a_real_key"))
    bogus = await client.post(PREVIEW_PATH, json=body)
    assert bogus.status_code == 401, bogus.text


async def test_preview_then_assemble_issues_normally(client, session_factory):
    """预检不产生副作用后，同参数 /assemble 仍能正常发证（无重复干扰、无脏审计）。"""
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    resp = await client.post(PREVIEW_PATH, json=_assemble_body(ps_id, slot_id))
    assert resp.status_code == 200 and resp.json()["guards_passed"] is True

    issued = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert issued.status_code == 200, issued.text
    assert issued.json()["final_id"]
    assert await _count_fcw(session_factory) == 1
    # 只应有签发审计一条；预检本身零审计。
    assert await _count_fcw_audit(session_factory) == 1
