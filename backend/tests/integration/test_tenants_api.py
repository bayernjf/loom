"""租户注册表 + 生命周期 + 段1 准入闸集成测试（Q95，09 D3.11）。

platform_admin 开通/列表/详情（派生 Onboarding 进度）/改套餐/暂停/恢复全程审计；
POST /api/intakes 对未知租户 404、暂停租户 409（应用层闸，无硬外键）。
团队/账号与真实认证随 V2，本切片不做成员绑定。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.tenants.models import TRIAL_MONTHLY_TOKEN_QUOTA, Tenant
from app.main import app
from app.product.product_intake.models import (
    ProductIntakeApplication,
    ProductSpace,
)

ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
NOBODY = {"id": "nobody-1", "roles": []}
OPS = {"id": "ops-1", "roles": ["operations"]}


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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _admin_params():
    return [("actor_id", ADMIN["id"]), ("roles", "platform_admin")]


# ---------- RBAC ----------


async def test_admin_rbac_gates(client):
    # 写端点 actor 在体：非 platform_admin 一律 403。
    r = await client.post(
        "/api/admin/tenants",
        json={"tenant_id": "t1", "actor": NOBODY},
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/admin/tenants",
        json={"tenant_id": "t1", "actor": OPS},
    )
    assert r.status_code == 403

    # GET 管理面：缺 actor_id → 422；角色不符 → 403。
    r = await client.get("/api/admin/tenants")
    assert r.status_code == 422
    r = await client.get(
        "/api/admin/tenants",
        params=[("actor_id", NOBODY["id"]), ("roles", "operations")],
    )
    assert r.status_code == 403


# ---------- 开通 ----------


async def test_provision_defaults_to_trial_with_quota(client, session_factory):
    r = await client.post(
        "/api/admin/tenants",
        json={"tenant_id": "t-trial", "name": "试用客户", "actor": ADMIN},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plan"] == "trial"
    assert body["status"] == "trial"
    assert body["monthly_token_quota"] == TRIAL_MONTHLY_TOKEN_QUOTA
    assert body["detail"] == {}

    r = await client.get("/api/admin/tenants/t-trial", params=_admin_params())
    assert r.status_code == 200, r.text
    assert r.json()["onboarding"] == {
        "intakes": 0,
        "product_spaces": 0,
        "first_modeling_started": False,
    }

    async with session_factory() as session:
        audit = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "tenant.provisioned")
            )
        ).all()
        assert len(audit) == 1 and audit[0].entity_id == "t-trial"


async def test_provision_paid_plan_starts_active_without_quota(client):
    r = await client.post(
        "/api/admin/tenants",
        json={"tenant_id": "t-pro", "name": "企业客户", "plan": "pro", "actor": ADMIN},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plan"] == "pro"
    assert body["status"] == "active"
    # 付费档额度原文未给【待补】：不落任何猜测值。
    assert body["monthly_token_quota"] is None


async def test_provision_rejects_duplicate_and_unknown_plan(client):
    await client.post(
        "/api/admin/tenants", json={"tenant_id": "t1", "actor": ADMIN}
    )
    r = await client.post(
        "/api/admin/tenants", json={"tenant_id": "t1", "actor": ADMIN}
    )
    assert r.status_code == 409
    r = await client.post(
        "/api/admin/tenants",
        json={"tenant_id": "t2", "plan": "platinum", "actor": ADMIN},
    )
    assert r.status_code == 422
    r = await client.get("/api/admin/tenants/missing", params=_admin_params())
    assert r.status_code == 404


# ---------- 生命周期 ----------


async def test_lifecycle_pause_blocks_intake_and_resume_reopens(client, session_factory):
    # 付费档开通 active。
    r = await client.post(
        "/api/admin/tenants",
        json={"tenant_id": "t1", "plan": "basic", "actor": ADMIN},
    )
    assert r.status_code == 201
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t1", "profile": {"f_name": "面霜"}}
    )
    assert r.status_code == 201, r.text

    r = await client.post("/api/admin/tenants/t1/pause", json={"actor": ADMIN})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paused"

    # 重复暂停 → 409。
    r = await client.post("/api/admin/tenants/t1/pause", json={"actor": ADMIN})
    assert r.status_code == 409

    # 段1 准入闸：暂停租户拒登。
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t1", "profile": {"f_name": "面霜2"}}
    )
    assert r.status_code == 409

    r = await client.post("/api/admin/tenants/t1/resume", json={"actor": ADMIN})
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t1", "profile": {"f_name": "面霜3"}}
    )
    assert r.status_code == 201, r.text

    # 未暂停时恢复 → 409。
    r = await client.post("/api/admin/tenants/t1/resume", json={"actor": ADMIN})
    assert r.status_code == 409

    async with session_factory() as session:
        actions = list(
            (
                await session.scalars(
                    select(AuditLog.action).where(AuditLog.entity_type == "tenant")
                )
            ).all()
        )
    # 同秒时间戳+uuid 主键下顺序不稳，按集合断言三类审计各一条。
    assert sorted(actions) == [
        "tenant.paused",
        "tenant.provisioned",
        "tenant.resumed",
    ]


async def test_change_plan_keeps_status_and_manages_quota(client):
    # 试用开通 → status=trial；改套餐（续费口径）不动 status。
    await client.post(
        "/api/admin/tenants", json={"tenant_id": "t1", "actor": ADMIN}
    )
    r = await client.post(
        "/api/admin/tenants/t1/change-plan",
        json={"plan": "enterprise", "actor": ADMIN},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] == "enterprise"
    assert body["status"] == "trial"  # 续费/改套餐不改状态（Q95 接缝②）
    assert body["monthly_token_quota"] is None  # 付费档额度【待补】

    # 非管理员拒绝。
    r = await client.post(
        "/api/admin/tenants/t1/change-plan",
        json={"plan": "basic", "actor": NOBODY},
    )
    assert r.status_code == 403

    # 暂停/恢复后状态为 active；再改套餐仍不动 status。
    await client.post("/api/admin/tenants/t1/pause", json={"actor": ADMIN})
    await client.post("/api/admin/tenants/t1/resume", json={"actor": ADMIN})
    r = await client.post(
        "/api/admin/tenants/t1/change-plan",
        json={"plan": "trial", "actor": ADMIN},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "trial" and body["status"] == "active"
    assert body["monthly_token_quota"] == TRIAL_MONTHLY_TOKEN_QUOTA


# ---------- 段1 准入：未知租户 ----------


async def test_unknown_tenant_writes_nothing(client, session_factory):
    r = await client.post(
        "/api/intakes", json={"tenant_id": "ghost", "profile": {"f_name": "面霜"}}
    )
    assert r.status_code == 404
    async with session_factory() as session:
        rows = (await session.scalars(select(ProductIntakeApplication))).all()
        assert rows == []
        audits = (await session.scalars(select(AuditLog))).all()
        assert audits == []


# ---------- 客户侧只读账户视图（Q114） ----------


async def test_customer_tenant_read(client):
    # 开通后客户侧可只读拿账户面板字段（无 admin 闸、无写审计）。
    await client.post(
        "/api/admin/tenants", json={"tenant_id": "t1", "name": "账户客户", "actor": ADMIN}
    )
    r = await client.get("/api/tenants/t1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "t1"
    assert body["name"] == "账户客户"
    assert body["plan"] == "trial"
    assert body["status"] == "trial"
    assert body["monthly_token_quota"] == TRIAL_MONTHLY_TOKEN_QUOTA
    # 客户视图不含管理面字段（detail/onboarding 不泄漏）。
    assert "detail" not in body
    assert "onboarding" not in body
    assert "created_at" not in body

    # 未知租户 404（只读，不写审计）。
    r = await client.get("/api/tenants/ghost")
    assert r.status_code == 404


# ---------- 详情：派生 Onboarding 进度 ----------


async def test_detail_onboarding_progress_derived(client, session_factory):
    await client.post(
        "/api/admin/tenants",
        json={"tenant_id": "t1", "plan": "basic", "actor": ADMIN},
    )
    async with session_factory() as session:
        intake = ProductIntakeApplication(tenant_id="t1", status="stored", profile={})
        session.add(intake)
        await session.flush()
        session.add_all([
            ProductSpace(
                tenant_id="t1", intake_id=intake.intake_id,
                lifecycle="modeling", profile_snapshot={},
            ),
        ])
        intake2 = ProductIntakeApplication(tenant_id="t1", status="draft", profile={})
        session.add(intake2)
        await session.commit()

    r = await client.get("/api/admin/tenants/t1", params=_admin_params())
    assert r.status_code == 200, r.text
    progress = r.json()["onboarding"]
    assert progress == {
        "intakes": 2,
        "product_spaces": 1,
        "first_modeling_started": True,
    }


# ---------- 列表 ----------


async def test_list_tenants_returns_all(client):
    for tid in ("t-b", "t-a"):
        r = await client.post(
            "/api/admin/tenants", json={"tenant_id": tid, "actor": ADMIN}
        )
        assert r.status_code == 201
    r = await client.get("/api/admin/tenants", params=_admin_params())
    assert r.status_code == 200, r.text
    rows = r.json()
    assert {row["tenant_id"] for row in rows} == {"t-b", "t-a"}


# ---------- 0023 回填行口径（detail 标记） ----------


async def test_backfilled_tenant_row_is_admitted(client, session_factory):
    # 模拟 0023 迁移回填行：basic/active + detail.backfilled。
    async with session_factory() as session:
        session.add(
            Tenant(
                tenant_id="legacy",
                name=None,
                plan="basic",
                status="active",
                monthly_token_quota=None,
                detail={
                    "backfilled": True,
                    "reason": "0023 pre-registry tenant_id backfill",
                },
                created_by="system-migration-0023",
            )
        )
        await session.commit()

    r = await client.post(
        "/api/intakes", json={"tenant_id": "legacy", "profile": {"f_name": "老品"}}
    )
    assert r.status_code == 201, r.text
    body = (
        await client.get("/api/admin/tenants/legacy", params=_admin_params())
    ).json()
    assert body["detail"]["backfilled"] is True
