"""Q177 D3.5 白名单组装引擎运营只读首片：管理端 FCW 列表 + 六层原料包内嵌口。

两个口都过 query actor 闸（operations|platform_admin），同 Q109/Q118/Q125/Q130：
缺 actor_id 由 FastAPI 判 422、角色不符判 403。复用 test_fcw_api 的全链路发证
helper（冻结→静态输入→CCR→组装）。本片零迁移、只读、不触发 Guard、不写审计。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
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
from tests.integration.test_fcw_api import (
    COMPLIANCE,
    GOAL,
    NOBODY,
    OPS,
    OWNER,
    PLATFORM,
    _assemble_body,
    _freeze,
    _make_ps,
)

PLATFORM_ADMIN = {"id": "admin-1", "roles": ["platform_admin"]}


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


async def _seed_inputs(client, ps_id: str, code: str = "xs-01") -> str:
    """复刻 test_fcw_api._seed_static_inputs，但发布位 code 可参数化。

    同库发第二条 FCW 时全局唯一 slot code 不能再用 xs-01（409 slot code taken），
    故本地版本允许 xs-02；PCP/三包按产品空间建，不跨租户冲突。
    """

    slot = await client.post(
        "/api/admin/publish-slots",
        json={"item": {
            "platform": PLATFORM, "code": code, "name": f"短视频位{code}",
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


async def _issue(client, session_factory, *, tenant: str, slot_code: str = "xs-01") -> dict:
    """在指定租户下走完整发证链路，返回一条已发证 FCW view。"""

    ps_id = await _make_ps(session_factory, tenant=tenant)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_inputs(client, ps_id, slot_code)
    run = await client.post(
        f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE}
    )
    assert run.status_code == 200, run.text
    issued = await client.post(
        "/api/fcw/assemble", json=_assemble_body(ps_id, slot_id)
    )
    assert issued.status_code == 200, issued.text
    return issued.json()


def _actor_params(actor: dict) -> list[tuple[str, str]]:
    return [("actor_id", actor["id"])] + [("roles", r) for r in actor["roles"]]


async def test_admin_list_requires_actor(client, session_factory):
    await _issue(client, session_factory, tenant="t1")
    # 缺 actor_id：FastAPI Query(...) 直接 422。
    resp = await client.get("/api/admin/fcw")
    assert resp.status_code == 422


@pytest.mark.parametrize("actor", [OWNER, NOBODY])
async def test_admin_list_forbidden_for_non_ops_admin(client, session_factory, actor):
    await _issue(client, session_factory, tenant="t1")
    resp = await client.get("/api/admin/fcw", params=_actor_params(actor))
    assert resp.status_code == 403


async def test_admin_list_cross_tenant_and_tenant_filter(client, session_factory):
    fcw_t1 = await _issue(client, session_factory, tenant="t1")
    fcw_t2 = await _issue(client, session_factory, tenant="t2", slot_code="xs-02")

    # operations 跨租户看到全部两条。
    resp = await client.get("/api/admin/fcw", params=_actor_params(OPS))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2 and body["count"] == 2
    assert body["limit"] == 50 and body["offset"] == 0 and body["has_more"] is False
    ids = {item["final_id"] for item in body["items"]}
    assert ids == {fcw_t1["final_id"], fcw_t2["final_id"]}
    # 元信息行即 fcw_view，不含六层大包。
    assert "layers" not in body["items"][0]
    assert {"tenant_id", "platform", "goal", "score", "publish_status"} <= set(
        body["items"][0]
    )

    # tenant_id 过滤只看一个租户。
    filtered = await client.get(
        "/api/admin/fcw",
        params=_actor_params(OPS) + [("tenant_id", "t2")],
    )
    assert filtered.status_code == 200
    fbody = filtered.json()
    assert fbody["total"] == 1 and fbody["count"] == 1
    assert fbody["items"][0]["final_id"] == fcw_t2["final_id"]
    assert fbody["items"][0]["tenant_id"] == "t2"

    # platform_admin 同样可读。
    admin_resp = await client.get(
        "/api/admin/fcw", params=_actor_params(PLATFORM_ADMIN)
    )
    assert admin_resp.status_code == 200
    assert admin_resp.json()["total"] == 2


async def test_admin_list_pagination(client, session_factory):
    fcw_t1 = await _issue(client, session_factory, tenant="t1")
    fcw_t2 = await _issue(client, session_factory, tenant="t2", slot_code="xs-02")

    first = await client.get(
        "/api/admin/fcw", params=_actor_params(OPS) + [("limit", "1"), ("offset", "0")]
    )
    assert first.status_code == 200
    fb = first.json()
    assert fb["count"] == 1 and fb["total"] == 2 and fb["has_more"] is True

    second = await client.get(
        "/api/admin/fcw", params=_actor_params(OPS) + [("limit", "1"), ("offset", "1")]
    )
    sb = second.json()
    assert sb["count"] == 1 and sb["has_more"] is False
    # 两页不重不漏、合起来恰为两条。
    page_ids = {fb["items"][0]["final_id"], sb["items"][0]["final_id"]}
    assert page_ids == {fcw_t1["final_id"], fcw_t2["final_id"]}

    # limit 越界（>200）被 Query 约束判 422。
    bad = await client.get(
        "/api/admin/fcw", params=_actor_params(OPS) + [("limit", "201")]
    )
    assert bad.status_code == 422


async def test_admin_material_returns_inline_six_layer_pack(client, session_factory):
    fcw = await _issue(client, session_factory, tenant="t1")
    resp = await client.get(
        f"/api/admin/fcw/{fcw['final_id']}/material", params=_actor_params(OPS)
    )
    assert resp.status_code == 200, resp.text
    # 内嵌口不带 attachment 下载头（与 Q155 material.json 导出面相区别）。
    assert resp.headers.get("content-disposition") is None
    pack = resp.json()
    assert pack["schema"] == "loom.fcw.material-pack.v1"
    assert pack["final_id"] == fcw["final_id"]
    assert set(pack["layers"]) == {
        "product", "platform", "strategy", "structure", "expression", "compliance"
    }

    # platform_admin 也可读。
    admin_resp = await client.get(
        f"/api/admin/fcw/{fcw['final_id']}/material",
        params=_actor_params(PLATFORM_ADMIN),
    )
    assert admin_resp.status_code == 200


async def test_admin_material_forbidden_and_unknown_404(client, session_factory):
    fcw = await _issue(client, session_factory, tenant="t1")
    # 客户/无角色越权 403。
    denied = await client.get(
        f"/api/admin/fcw/{fcw['final_id']}/material", params=_actor_params(OWNER)
    )
    assert denied.status_code == 403
    # 缺 actor 422。
    assert (await client.get(f"/api/admin/fcw/{fcw['final_id']}/material")).status_code == 422
    # operations 查未知 final_id 404。
    missing = await client.get(
        "/api/admin/fcw/nonexistent-id/material", params=_actor_params(OPS)
    )
    assert missing.status_code == 404
