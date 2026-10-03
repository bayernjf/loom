"""段9 红旗 A6 验证性收口：layerSpaces 共享原子参与组装不破坏 FCW Guard 实例归属校验（Q52 口径）。

背景：A6 已由 Q52 裁决解除——区分"底座选项"（全租户共享字典，layer_space_items 无
product_space_id）与"配置实例"（三包落库即带 product_space_id + tenant_id），段11
Guard④⑤ 校验**实例**归属而非底座归属。Q262 建底座时"不触碰 FCW"，本片补集成验证钉住
Q52 口径在真实组装链路上成立。

覆盖：
- 包 payload 引用跨租户共享的 layerSpace 原子（无 product_space_id 归属），
  FCW 组装 Guard G4/G5 仍按包实例归属工作（共享的是字典、校验的是实例）；
- 另一 PS（不同租户）复用同一原子组装同样通过（原子跨 PS 共享语义成立）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.staff_auth.deps import get_auth_session
from app.decision.layer_strategy.models import LayerSpace, LayerSpaceItem
from app.decision.layer_strategy.seeds import LAYER_DIMENSIONS
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
)

SHARED_ATOM = "种草"  # strategy 层共享原子名（跨租户字典，无 product_space_id）


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
        session.add_all(
            [
                LayerSpace(
                    layer_id=f"layer-{code}",
                    code=code,
                    name=name,
                    dimensions=list(dims),
                    sort_order=order,
                )
                for order, (code, (name, dims)) in enumerate(
                    LAYER_DIMENSIONS.items(), start=1
                )
            ]
        )
        # 共享字典原子：strategy 层「种草」（formal，无 tenant_id / product_space_id）。
        strategy_layer = next(
            s for s in (await session.scalars(select(LayerSpace))).all()
            if s.code == "strategy"
        )
        session.add(
            LayerSpaceItem(
                layer_id=strategy_layer.layer_id,
                dimension="goal",
                name=SHARED_ATOM,
                status="formal",
                created_by="s-pa",
            )
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


async def _seed_ps_with_atom_payload(client, ps_id, slot_code):
    """造一个引用共享原子的 PS：slot + PCP + 三包（payload 值含共享原子名）。"""
    slot = await client.post(
        "/api/admin/publish-slots",
        json={"item": {
            "platform": PLATFORM, "code": slot_code, "name": "短视频位",
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
        "csp": {"goal": SHARED_ATOM, "stage": "认知", "angle": "成分",
                "intensity": "中", "cta": "软", "emotion": "安心"},
        "cstp": {"struct": "钩子-论点-收尾"},
        "cep": {"tone": "温和", "perspective": "第二人称",
                "explicit": "低", "soften": "轻"},
    }
    for kind, payload in payloads.items():
        resp = await client.post(
            f"/api/product-spaces/{ps_id}/packages",
            json={"item": {
                "kind": kind, "platform": PLATFORM, "goal": "ENGAGEMENT",
                "payload": payload, "conf": 0.8,
            }, "actor": OPS},
        )
        assert resp.status_code == 201, resp.text
    return slot_id


async def _assemble(client, ps_id, pws_id, slot_id) -> dict:
    await client.post(f"/api/pws/{pws_id}/ccr/run", json={"actor": COMPLIANCE})
    resp = await client.post("/api/fcw/assemble", json={
        "product_space_id": ps_id, "platform": PLATFORM, "slot_id": slot_id,
        "goal": "ENGAGEMENT", "actor": OPS,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_shared_atom_payload_passes_assembly_guards(client, session_factory):
    """包 payload 引用无归属共享原子，Guard 仍按包实例归属放行。"""
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_ps_with_atom_payload(client, ps_id, "xs-01")
    fcw = await _assemble(client, ps_id, pws["pws_id"], slot_id)
    assert fcw["guards_passed"] is True, fcw


async def test_cross_ps_reuse_same_atom_passes(client, session_factory):
    """另一租户的 PS 复用同一共享原子组装同样通过（原子跨 PS 共享成立）。"""
    ps1 = await _make_ps(session_factory)
    pws1 = await _freeze(client, ps1)
    slot1 = await _seed_ps_with_atom_payload(client, ps1, "xs-01")
    fcw1 = await _assemble(client, ps1, pws1["pws_id"], slot1)
    assert fcw1["guards_passed"] is True, fcw1

    ps2 = await _make_ps(session_factory, tenant="t2")
    pws2 = await _freeze(client, ps2)
    slot2 = await _seed_ps_with_atom_payload(client, ps2, "xs-02")
    fcw2 = await _assemble(client, ps2, pws2["pws_id"], slot2)
    assert fcw2["guards_passed"] is True, fcw2
    assert fcw2["final_id"] != fcw1["final_id"], "不同 PS 各自发证、final_id 独立"
