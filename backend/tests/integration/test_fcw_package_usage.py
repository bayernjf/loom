"""段11 FCW 发证对段9 三包的 usage_count 递增 + 阈值触发审计（Q263，Q45 落地）。

覆盖：
- 单条发证成功 → csp/cstp/cep 三包 usage_count 各 +1；
- 跨过 package.reuse_threshold → 写 package.reuse_threshold_reached 审计；
- 未跨阈值 → 不写触发审计；
- 批量任务（Q55）发证同样递增；
- 发证失败（Guard 不全绿）→ 不递增（不发证即不使用）。
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
    _assemble_body,
    _freeze,
    _make_ps,
    _seed_static_inputs,
)

REUSE_THRESHOLD_KEY = "package.reuse_threshold"
ASSEMBLE_PATH = "/api/fcw/assemble"
TASK_PATH = "/api/fcw/assembly-tasks"


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
    """每个用例前把阈值复位到默认 20，用例内按需覆盖。"""
    config_cache.invalidate()
    yield
    config_cache.invalidate()


async def _counts(session_factory) -> dict[str, int]:
    async with session_factory() as session:
        rows = (await session.scalars(select(Package))).all()
        return {f"{p.kind}:{p.platform}:{p.goal}": p.usage_count for p in rows}


async def _trigger_audits(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "package.reuse_threshold_reached"
                )
            )
        ).all()
        return [f"{r.entity_id}:{r.detail.get('usage_count')}" for r in rows]


async def test_assemble_increments_all_three_packages(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    resp = await client.post(ASSEMBLE_PATH, json=_assemble_body(ps_id, slot_id))
    assert resp.status_code == 200, resp.text
    counts = await _counts(session_factory)
    assert len(counts) == 3, counts
    assert all(v == 1 for v in counts.values()), counts
    # 默认阈值 20：一次发证不触发。
    assert await _trigger_audits(session_factory) == []


async def test_second_issue_increments_again_without_trigger(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    # 再建一个发布位，让第二次发证走不同 slot（同 slot 重复发证 409）。
    slot2_resp = await client.post(
        "/api/admin/publish-slots",
        json={"item": {
            "platform": PLATFORM, "code": "xs-02", "name": "位2",
            "slot_type": "short_video",
            "traffic": 50, "safe": 50, "conv": 50, "load": 50,
        }, "actor": OPS},
    )
    slot2 = slot2_resp.json()["slot_id"]
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    for sid in (slot_id, slot2):
        resp = await client.post(ASSEMBLE_PATH, json=_assemble_body(ps_id, sid))
        assert resp.status_code == 200, resp.text
    counts = await _counts(session_factory)
    assert all(v == 2 for v in counts.values()), counts
    assert await _trigger_audits(session_factory) == []


async def test_crossing_threshold_writes_audit_once(client, session_factory):
    config_cache.apply({REUSE_THRESHOLD_KEY: 2}, versions={REUSE_THRESHOLD_KEY: 1})
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    slot2_resp = await client.post(
        "/api/admin/publish-slots",
        json={"item": {
            "platform": PLATFORM, "code": "xs-02", "name": "位2",
            "slot_type": "short_video",
            "traffic": 50, "safe": 50, "conv": 50, "load": 50,
        }, "actor": OPS},
    )
    slot2 = slot2_resp.json()["slot_id"]
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    for sid in (slot_id, slot2):
        resp = await client.post(ASSEMBLE_PATH, json=_assemble_body(ps_id, sid))
        assert resp.status_code == 200, resp.text
    audits = await _trigger_audits(session_factory)
    # 三个包各跨一次阈值 → 3 条审计。
    assert len(audits) == 3, audits
    assert all(audit.endswith(":2") for audit in audits), audits
    # 再发一次：已跨过，不再重复触发。
    slot3_resp = await client.post(
        "/api/admin/publish-slots",
        json={"item": {
            "platform": PLATFORM, "code": "xs-03", "name": "位3",
            "slot_type": "short_video",
            "traffic": 50, "safe": 50, "conv": 50, "load": 50,
        }, "actor": OPS},
    )
    slot3 = slot3_resp.json()["slot_id"]
    resp = await client.post(ASSEMBLE_PATH, json=_assemble_body(ps_id, slot3))
    assert resp.status_code == 200, resp.text
    assert len(await _trigger_audits(session_factory)) == 3


async def test_batch_task_increments_packages(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    slot2_resp = await client.post(
        "/api/admin/publish-slots",
        json={"item": {
            "platform": PLATFORM, "code": "xs-02", "name": "位2",
            "slot_type": "short_video",
            "traffic": 50, "safe": 50, "conv": 50, "load": 50,
        }, "actor": OPS},
    )
    slot2 = slot2_resp.json()["slot_id"]
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    resp = await client.post(
        TASK_PATH,
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": "ENGAGEMENT",
            "count": 2, "slot_ids": [slot_id, slot2], "actor": OPS,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert len(body["results"]["issued"]) == 2
    counts = await _counts(session_factory)
    assert all(v == 2 for v in counts.values()), counts


async def test_blocked_assembly_does_not_increment(client, session_factory):
    # 不发证（Guard 不齐）不递增：无 slot 且无 CCR → 404/409，包计数保持 0。
    ps_id = await _make_ps(session_factory)
    await _freeze(client, ps_id)
    resp = await client.post(
        ASSEMBLE_PATH,
        json=_assemble_body(ps_id, "no-such-slot"),
    )
    assert resp.status_code == 404, resp.text
    counts = await _counts(session_factory)
    assert counts == {}, counts
    assert await _trigger_audits(session_factory) == []
