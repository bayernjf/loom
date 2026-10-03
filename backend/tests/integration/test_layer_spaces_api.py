"""Q262 集成测试：layerSpaces 通用底座 API（Q46）。

覆盖：管理面读口 query actor 闸（缺 actor 422 / 角色 403 / 命中 200 且四层
22 维度种子完整）、写口只认已验真 staff 令牌（无令牌 401 / ops 403 /
platform_admin 201）、维度与状态校验、同键唯一与软归档复活、影响面统计与
变更确认 Gate（活跃配方引用 → 改名/归档 409 → confirmed 通过）、审计。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.staff_auth.deps import get_auth_session
from app.decision.layer_strategy.models import LayerSpace, Package
from app.decision.layer_strategy.seeds import LAYER_DIMENSIONS
from app.main import app
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.product_intake.models import ProductIntakeApplication, ProductSpace
from tests.integration.staff_tokens import bearer, issue_staff_token

OPS = {"id": "ops-1", "roles": ["operations"]}
PA = {"id": "pa-1", "roles": ["platform_admin"]}


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
        session.add_all([ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS])
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
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _pa_token(client) -> str:
    return await issue_staff_token(
        client, ["platform_admin"], staff_id="s-pa", staff_name="平台管理员"
    )


async def _ops_token(client) -> str:
    return await issue_staff_token(
        client, ["operations"], staff_id="s-ops", staff_name="运营值班"
    )


async def _first_layer(session_factory):
    async with session_factory() as session:
        layer = (await session.scalars(select(LayerSpace))).first()
        return layer


async def _make_ps_and_package(session_factory, *, name: str, tenant: str = "t1"):
    """造 ProductSpace + 引用某原子的 CSP package（活跃配方），返回 atom 名。"""
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id=tenant, status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        session.add(
            ProductSpace(
                product_space_id="ps-1",
                tenant_id=tenant,
                intake_id=intake.intake_id,
                industry_tag="general",
                profile_snapshot={"f_a": "x"},
            )
        )
        session.add(
            Package(
                kind="csp",
                tenant_id=tenant,
                product_space_id="ps-1",
                platform="x_platform",
                goal="ENGAGEMENT",
                payload={"stage": name, "goal": "ENGAGEMENT"},
            )
        )
        await session.commit()


# ---------- 读口 ----------


async def test_read_requires_actor_query(client, session_factory):
    missing = await client.get("/api/admin/layer-spaces")
    assert missing.status_code == 422

    denied = await client.get(
        "/api/admin/layer-spaces", params={"actor_id": "nobody", "roles": "[]"}
    )
    assert denied.status_code == 403

    ok = await client.get(
        "/api/admin/layer-spaces",
        params={"actor_id": "ops-1", "roles": "operations"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert len(body) == 4
    codes = [layer["code"] for layer in body]
    assert codes == ["strategy", "structure", "expression", "compliance"]
    dims = sum(len(layer["dimensions"]) for layer in body)
    assert dims == 22  # 6+6+6+4（04 §2.16，line 1261）


async def test_impact_read_requires_actor_query(client):
    missing = await client.get(
        "/api/admin/layer-spaces/items/i-1/impact"
    )
    assert missing.status_code == 422
    denied = await client.get(
        "/api/admin/layer-spaces/items/i-1/impact",
        params={"actor_id": "nobody", "roles": "[]"},
    )
    assert denied.status_code == 403


# ---------- 写口鉴权 ----------


async def test_write_requires_internal_token(client, session_factory):
    layer = await _first_layer(session_factory)
    body = {
        "layer_id": layer.layer_id,
        "dimension": layer.dimensions[0],
        "name": "感知",
        "status": "formal",
        "actor": PA,
    }
    no_token = await client.post("/api/admin/layer-spaces/items", json=body)
    assert no_token.status_code == 401

    ops_token = await _ops_token(client)
    ops_denied = await client.post(
        "/api/admin/layer-spaces/items",
        json=body,
        headers=bearer(ops_token),
    )
    assert ops_denied.status_code == 403

    pa_token = await _pa_token(client)
    created = await client.post(
        "/api/admin/layer-spaces/items", json=body, headers=bearer(pa_token)
    )
    assert created.status_code == 201
    assert created.json()["name"] == "感知"


# ---------- 创建校验 ----------


async def test_create_validation_and_duplicate(client, session_factory):
    pa_token = await _pa_token(client)
    layer = await _first_layer(session_factory)

    unknown_layer = await client.post(
        "/api/admin/layer-spaces/items",
        json={
            "layer_id": "nope",
            "dimension": "x",
            "name": "x",
            "status": "formal",
            "actor": PA,
        },
        headers=bearer(pa_token),
    )
    assert unknown_layer.status_code == 404

    bad_dim = await client.post(
        "/api/admin/layer-spaces/items",
        json={
            "layer_id": layer.layer_id,
            "dimension": "不存在的维度",
            "name": "x",
            "status": "formal",
            "actor": PA,
        },
        headers=bearer(pa_token),
    )
    assert bad_dim.status_code == 422
    assert bad_dim.json()["detail"]["violations"][0].startswith("unknown_dimension:")

    bad_status = await client.post(
        "/api/admin/layer-spaces/items",
        json={
            "layer_id": layer.layer_id,
            "dimension": layer.dimensions[0],
            "name": "x",
            "status": "bogus",
            "actor": PA,
        },
        headers=bearer(pa_token),
    )
    assert bad_status.status_code == 422

    body = {
        "layer_id": layer.layer_id,
        "dimension": layer.dimensions[0],
        "name": "唯一原子",
        "status": "formal",
        "actor": PA,
    }
    ok = await client.post(
        "/api/admin/layer-spaces/items", json=body, headers=bearer(pa_token)
    )
    assert ok.status_code == 201

    dup = await client.post(
        "/api/admin/layer-spaces/items", json=body, headers=bearer(pa_token)
    )
    assert dup.status_code == 409

    # 软归档后可重建（字典先例）：DELETE 无引用无需确认 → 204 → 再建 201。
    item_id = ok.json()["item_id"]
    arc = await client.request(
        "DELETE",
        f"/api/admin/layer-spaces/items/{item_id}",
        json={"impact_confirmed": False, "actor": PA},
        headers=bearer(pa_token),
    )
    assert arc.status_code == 204
    revive = await client.post(
        "/api/admin/layer-spaces/items", json=body, headers=bearer(pa_token)
    )
    assert revive.status_code == 201


# ---------- 影响面 Gate ----------


async def test_impact_gate_flow(client, session_factory):
    pa_token = await _pa_token(client)
    layer = await _first_layer(session_factory)
    atom = "被引原子"
    created = await client.post(
        "/api/admin/layer-spaces/items",
        json={
            "layer_id": layer.layer_id,
            "dimension": layer.dimensions[0],
            "name": atom,
            "status": "formal",
            "actor": PA,
        },
        headers=bearer(pa_token),
    )
    assert created.status_code == 201
    item_id = created.json()["item_id"]

    # 尚无引用 → impact 0。
    impact = await client.get(
        f"/api/admin/layer-spaces/items/{item_id}/impact",
        params={"actor_id": "ops-1", "roles": "operations"},
    )
    assert impact.status_code == 200
    assert impact.json()["active_package_refs"] == 0

    # 造活跃配方（CSP package payload 引用该原子）。
    await _make_ps_and_package(session_factory, name=atom)
    impact = await client.get(
        f"/api/admin/layer-spaces/items/{item_id}/impact",
        params={"actor_id": "ops-1", "roles": "operations"},
    )
    assert impact.json()["active_package_refs"] == 1

    # 改名无确认 → 409 带影响数。
    rename = await client.put(
        f"/api/admin/layer-spaces/items/{item_id}",
        json={"name": "新原子", "status": None, "impact_confirmed": False, "actor": PA},
        headers=bearer(pa_token),
    )
    assert rename.status_code == 409
    assert rename.json()["detail"]["active_package_refs"] == 1

    # 归档同理：改名之前引用仍在 → 无确认 409。
    arc_denied = await client.request(
        "DELETE",
        f"/api/admin/layer-spaces/items/{item_id}",
        json={"impact_confirmed": False, "actor": PA},
        headers=bearer(pa_token),
    )
    assert arc_denied.status_code == 409

    # 确认后改名通过（改名后 payload 引用旧值自然断开，工程口径【实现补】）。
    renamed = await client.put(
        f"/api/admin/layer-spaces/items/{item_id}",
        json={"name": "新原子", "status": None, "impact_confirmed": True, "actor": PA},
        headers=bearer(pa_token),
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "新原子"

    arc_ok = await client.request(
        "DELETE",
        f"/api/admin/layer-spaces/items/{item_id}",
        json={"impact_confirmed": True, "actor": PA},
        headers=bearer(pa_token),
    )
    assert arc_ok.status_code == 204

    gone = await client.get(
        f"/api/admin/layer-spaces/items/{item_id}/impact",
        params={"actor_id": "ops-1", "roles": "operations"},
    )
    assert gone.status_code == 404


# ---------- 审计 ----------


async def test_writes_are_audited_as_platform(client, session_factory):
    pa_token = await _pa_token(client)
    layer = await _first_layer(session_factory)
    created = await client.post(
        "/api/admin/layer-spaces/items",
        json={
            "layer_id": layer.layer_id,
            "dimension": layer.dimensions[0],
            "name": "审计原子",
            "status": "candidate",
            "actor": PA,
        },
        headers=bearer(pa_token),
    )
    assert created.status_code == 201
    item_id = created.json()["item_id"]
    await client.put(
        f"/api/admin/layer-spaces/items/{item_id}",
        json={"name": None, "status": "frozen", "impact_confirmed": False, "actor": PA},
        headers=bearer(pa_token),
    )
    await client.request(
        "DELETE",
        f"/api/admin/layer-spaces/items/{item_id}",
        json={"impact_confirmed": False, "actor": PA},
        headers=bearer(pa_token),
    )

    async with session_factory() as session:
        actions = list(
            (
                await session.scalars(
                    select(AuditLog).where(AuditLog.entity_type == "layer_space_item")
                )
            ).all()
        )
        seen = {row.action for row in actions}
        assert seen == {
            "layer_space.item_create",
            "layer_space.item_update",
            "layer_space.item_archive",
        }
        assert all(row.tenant_id == "_platform" for row in actions)
        assert all(row.actor_id == "s-pa" for row in actions)
