from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.tenants.models import Tenant
from app.main import app
from app.product.condition.models import ContentGoal
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import G2Field
from tests.integration.client_tokens import client_bearer, issue_client_token
from tests.integration.staff_tokens import bearer, issue_write_token


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
    # Q95：段1 准入闸要求租户已注册且未暂停。
    async with session_factory() as session:
        session.add(Tenant(tenant_id="t1", name="试点客户", plan="basic", status="active"))
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # P1-1：intakes 面全部要凭证。默认 staff 令牌（operations 等三写角色），
        # 客户令牌路径由 test_p11_* 用例单独覆盖。
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


@pytest_asyncio.fixture
async def seeded_common_fields(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                G2Field(fid="f_name", cat="common", field_name="产品名"),
                G2Field(fid="f_brief", cat="common", field_name="简介"),
                G2Field(fid="x_deprecated", cat="common", field_name="废弃字段",
                        status="deprecated"),
            ]
        )
        await session.commit()


OPS = {"id": "ops-1", "roles": ["operations"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


async def _fire(client, intake_id, event, actor=OPS, **extra):
    return await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": event, "actor": actor, **extra},
    )


async def test_submit_blocked_when_common_fields_missing(client, seeded_common_fields):
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t1", "profile": {"f_name": "面霜"}}
    )
    assert r.status_code == 201
    intake_id = r.json()["intake_id"]

    r = await _fire(client, intake_id, "submit", actor=CUSTOMER)
    assert r.status_code == 422
    assert r.json()["detail"]["missing_fids"] == ["f_brief"]


async def test_submit_content_usage_bound_to_goals_dictionary(client, session_factory):
    # Q25（Q362）：内容用途取值绑定 contentGoals 目的字典——录入页与 PWC 打标
    # 读同一张表；提交闸拒收自由文本与已归档码，active 枚举码放行。
    async with session_factory() as session:
        session.add_all(
            [
                G2Field(fid="f_content_usage", cat="common", field_name="内容用途"),
                ContentGoal(code="ENGAGEMENT"),
                ContentGoal(code="TRUST", status="archived"),
            ]
        )
        await session.commit()

    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_content_usage": "种草"}},
    )
    assert r.status_code == 201
    intake_id = r.json()["intake_id"]

    bad = await _fire(client, intake_id, "submit", actor=CUSTOMER)
    assert bad.status_code == 422
    assert "contentGoals" in bad.text

    await client.patch(
        f"/api/intakes/{intake_id}/profile",
        json={"profile": {"f_content_usage": "TRUST"}, "actor": CUSTOMER},
    )
    archived = await _fire(client, intake_id, "submit", actor=CUSTOMER)
    assert archived.status_code == 422

    await client.patch(
        f"/api/intakes/{intake_id}/profile",
        json={"profile": {"f_content_usage": "ENGAGEMENT"}, "actor": CUSTOMER},
    )
    ok = await _fire(client, intake_id, "submit", actor=CUSTOMER)
    assert ok.status_code == 200, ok.text


async def test_full_flow_creates_ps_snapshot(client, seeded_common_fields):
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t1", "profile": {"f_name": "面霜"}}
    )
    intake_id = r.json()["intake_id"]

    r = await client.patch(
        f"/api/intakes/{intake_id}/profile",
        json={"profile": {"f_brief": "保湿修护"}, "actor": CUSTOMER},
    )
    assert r.status_code == 200

    for event, actor in [
        ("submit", CUSTOMER),
        ("wf01_confirm", OPS),
        ("ops_confirm", OPS),
        ("send_review", OPS),
        ("review_approve", OPS),
        ("start_modeling", OPS),
        ("model_stored", OPS),
    ]:
        r = await _fire(client, intake_id, event, actor=actor)
        assert r.status_code == 200, (event, r.text)
    assert r.json()["status"] == sm.STORED

    r = await client.get(f"/api/intakes/{intake_id}/product-space")
    assert r.status_code == 200
    body = r.json()
    assert body["lifecycle"] == sm.MODELING
    assert body["profile_snapshot"] == {"f_name": "面霜", "f_brief": "保湿修护"}

    # 入库后资料不可改（Q74 快照纪律）。
    r = await client.patch(
        f"/api/intakes/{intake_id}/profile",
        json={"profile": {"f_name": "篡改"}, "actor": CUSTOMER},
    )
    assert r.status_code == 409


async def test_list_intakes_empty_for_unknown_tenant(client):
    # Q98：读路径不触发 Q95 准入门，未知租户返回空列表而非 404。
    r = await client.get("/api/intakes", params={"tenant_id": "ghost"})
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_list_intakes_pagination_order_and_tenant_isolation(
    client, session_factory
):
    async with session_factory() as session:
        session.add(Tenant(tenant_id="t2", name="第二客户", plan="basic", status="active"))
        await session.commit()

    created = []
    for name in ["甲", "乙", "丙"]:
        r = await client.post(
            "/api/intakes",
            json={"tenant_id": "t1", "profile": {"product_name": name}},
        )
        assert r.status_code == 201
        created.append((name, r.json()["intake_id"]))
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t2", "profile": {"product_name": "他租户"}}
    )
    assert r.status_code == 201

    page1 = await client.get(
        "/api/intakes", params={"tenant_id": "t1", "limit": 2, "offset": 0}
    )
    assert page1.status_code == 200
    body = page1.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2

    page2 = await client.get(
        "/api/intakes", params={"tenant_id": "t1", "limit": 2, "offset": 2}
    )
    page_ids = [item["intake_id"] for item in body["items"]] + [
        item["intake_id"] for item in page2.json()["items"]
    ]
    # 两页恰好覆盖 t1 全部三单、不重不漏；created_at 倒序，同秒次序不作断言。
    assert sorted(page_ids) == sorted(intake_id for _, intake_id in created)

    other = await client.get("/api/intakes", params={"tenant_id": "t2"})
    assert other.json()["total"] == 1
    assert other.json()["items"][0]["profile"]["product_name"] == "他租户"


async def test_list_intakes_rejects_bad_params(client):
    assert (
        await client.get("/api/intakes", params={"tenant_id": "", "limit": 0})
    ).status_code == 422
    assert (
        await client.get(
            "/api/intakes", params={"tenant_id": "t1", "offset": -1}
        )
    ).status_code == 422


async def test_overview_empty_for_unknown_tenant(client):
    # Q99：读路径不触发 Q95 准入门；且 /overview 不得被 /{intake_id} 路由吞掉。
    r = await client.get("/api/intakes/overview", params={"tenant_id": "ghost"})
    assert r.status_code == 200
    assert r.json() == {"total": 0, "by_status": {}}


async def test_overview_groups_by_status_and_tenant(
    client, session_factory, seeded_common_fields
):
    async with session_factory() as session:
        session.add(Tenant(tenant_id="t2", name="第二客户", plan="basic", status="active"))
        await session.commit()

    for name in ["甲", "乙", "丙"]:
        r = await client.post(
            "/api/intakes", json={"tenant_id": "t1", "profile": {"product_name": name}}
        )
        assert r.status_code == 201

    # 资料完整的一单推进到已提交：草稿 -2、AI识别中→待确认→已提交各 +1。
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "面霜", "f_brief": "保湿"}},
    )
    moving_id = r.json()["intake_id"]
    await _fire(client, moving_id, "submit", actor=CUSTOMER)
    await _fire(client, moving_id, "wf01_confirm", actor=OPS)
    await _fire(client, moving_id, "ops_confirm", actor=OPS)

    r = await client.post(
        "/api/intakes", json={"tenant_id": "t2", "profile": {"product_name": "他租户"}}
    )
    assert r.status_code == 201

    r = await client.get("/api/intakes/overview", params={"tenant_id": "t1"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert body["by_status"] == {"draft": 3, "submitted": 1}

    r = await client.get("/api/intakes/overview", params={"tenant_id": "t2"})
    assert r.json() == {"total": 1, "by_status": {"draft": 1}}


async def test_overview_rejects_empty_tenant(client):
    assert (
        await client.get("/api/intakes/overview", params={"tenant_id": ""})
    ).status_code == 422


async def test_terminal_and_role_guards(client, seeded_common_fields):
    r = await client.post(
        "/api/intakes",
        json={
            "tenant_id": "t1",
            "profile": {"f_name": "x", "f_brief": "y"},
        },
    )
    intake_id = r.json()["intake_id"]
    await _fire(client, intake_id, "submit", actor=CUSTOMER)
    await _fire(client, intake_id, "wf01_confirm", actor=OPS)

    # 类目确认必须运营（Q3）。P1-1 起身份以令牌为准：客户令牌（whitelist_owner）
    # 触发同一角色闸；body 自报 CUSTOMER/OPS 均不作数。
    client_secret = await issue_client_token(client, "t1")
    r = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "ops_confirm", "actor": CUSTOMER},
        headers=client_bearer(client_secret),
    )
    assert r.status_code == 403

    await _fire(client, intake_id, "ops_confirm", actor=OPS)
    await _fire(client, intake_id, "send_review", actor=OPS)
    await _fire(client, intake_id, "review_reject", actor=OPS)

    r = await _fire(client, intake_id, "submit", actor=CUSTOMER)
    assert r.status_code == 409  # 驳回终态


# ---- Q107：运营跨租户队列 GET /api/intakes/ops-queue ----


async def test_ops_queue_requires_actor_and_ops_or_platform_role(client):
    # 缺 actor_id query → FastAPI 422；有身份但角色不符 → 403。
    assert (await client.get("/api/intakes/ops-queue")).status_code == 422
    r = await client.get(
        "/api/intakes/ops-queue",
        params=[("actor_id", "cust-1"), ("roles", "customer")],
    )
    assert r.status_code == 403

    for roles in [["operations"], ["platform_admin"]]:
        r = await client.get(
            "/api/intakes/ops-queue",
            params=[("actor_id", "admin-1"), *[("roles", role) for role in roles]],
        )
        assert r.status_code == 200, roles
        assert r.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_ops_queue_cross_tenant_status_filter_and_pagination(
    client, session_factory
):
    async with session_factory() as session:
        session.add(Tenant(tenant_id="t2", name="第二客户", plan="basic", status="active"))
        await session.commit()

    t1_ids = []
    for name in ["甲", "乙", "丙"]:
        r = await client.post(
            "/api/intakes", json={"tenant_id": "t1", "profile": {"product_name": name}}
        )
        t1_ids.append(r.json()["intake_id"])
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t2", "profile": {"product_name": "他租户"}}
    )
    t2_id = r.json()["intake_id"]

    ops_params = [("actor_id", "ops-1"), ("roles", "operations")]

    # 跨租户可见：t1 三单 + t2 一单，且行携带 created_at。
    r = await client.get("/api/intakes/ops-queue", params=ops_params)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert sorted(item["intake_id"] for item in body["items"]) == sorted(t1_ids + [t2_id])
    assert {item["tenant_id"] for item in body["items"]} == {"t1", "t2"}
    assert all("created_at" in item for item in body["items"])

    # 状态过滤：四单均为 draft；非法状态 422。
    r = await client.get("/api/intakes/ops-queue", params=[*ops_params, ("status", "draft")])
    assert r.json()["total"] == 4
    r = await client.get(
        "/api/intakes/ops-queue", params=[*ops_params, ("status", "submitted")]
    )
    assert r.json()["total"] == 0
    r = await client.get(
        "/api/intakes/ops-queue", params=[*ops_params, ("status", "not_a_state")]
    )
    assert r.status_code == 422

    # 分页：两页不重不漏覆盖四单。
    page1 = await client.get(
        "/api/intakes/ops-queue", params=[*ops_params, ("limit", "2"), ("offset", "0")]
    )
    assert page1.json()["limit"] == 2
    assert len(page1.json()["items"]) == 2
    page2 = await client.get(
        "/api/intakes/ops-queue", params=[*ops_params, ("limit", "2"), ("offset", "2")]
    )
    page_ids = [item["intake_id"] for item in page1.json()["items"]] + [
        item["intake_id"] for item in page2.json()["items"]
    ]
    assert sorted(page_ids) == sorted(t1_ids + [t2_id])


async def test_ops_queue_follows_transitions(client, seeded_common_fields):
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "面霜", "f_brief": "保湿"}},
    )
    intake_id = r.json()["intake_id"]
    await _fire(client, intake_id, "submit", actor=CUSTOMER)
    await _fire(client, intake_id, "wf01_confirm", actor=OPS)

    ops_params = [("actor_id", "ops-1"), ("roles", "operations"), ("status", "pending_confirm")]
    r = await client.get("/api/intakes/ops-queue", params=ops_params)
    assert r.status_code == 200
    assert [item["intake_id"] for item in r.json()["items"]] == [intake_id]

    # 运营确认推进到已提交后，pending_confirm 队列清空。
    assert (await _fire(client, intake_id, "ops_confirm", actor=OPS)).status_code == 200
    r = await client.get("/api/intakes/ops-queue", params=ops_params)
    assert r.json()["items"] == []
    r = await client.get(
        "/api/intakes/ops-queue",
        params=[("actor_id", "ops-1"), ("roles", "operations"), ("status", "submitted")],
    )
    assert [item["intake_id"] for item in r.json()["items"]] == [intake_id]


# ---------- Q350（清单二 #13 甲）：PS 行业旗标从 C1 识别 + Q7 阈值表派生 ----------

async def _to_approved(client, intake_id):
    await _fire(client, intake_id, "submit", actor=CUSTOMER)
    await _fire(client, intake_id, "wf01_confirm", actor=OPS)
    await _fire(client, intake_id, "ops_confirm", actor=OPS)
    await _fire(client, intake_id, "send_review", actor=OPS)
    await _fire(client, intake_id, "review_approve", actor=OPS)


async def _seed_industry_and_record(session_factory, *, intake_id, industry, sensitive):
    from app.product.modeling.models import C1IndustryThreshold, C1Record

    async with session_factory() as session:
        session.add(
            C1IndustryThreshold(
                industry=industry, keywords=[], threshold=0.85, sensitive=sensitive,
                enabled=True, is_default=False,
            )
        )
        session.add(
            C1Record(
                tenant_id="t1", intake_id=intake_id, signals={"text": 0.9}, conf=0.95,
                industry=industry, branch="direct_approve", top_candidates=[], top_gap=0.2,
            )
        )
        await session.commit()


async def test_start_modeling_derives_sensitive_flag_from_q7(
    client, session_factory, seeded_common_fields
):
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t1", "profile": {"f_name": "血压计", "f_brief": "医用"}}
    )
    intake_id = r.json()["intake_id"]
    await _to_approved(client, intake_id)
    await _seed_industry_and_record(
        session_factory, intake_id=intake_id, industry="medical", sensitive=True
    )

    assert (await _fire(client, intake_id, "start_modeling", actor=OPS)).status_code == 200

    from app.product.product_intake.models import ProductSpace

    async with session_factory() as session:
        ps = (
            await session.scalars(
                select(ProductSpace).where(ProductSpace.intake_id == intake_id)
            )
        ).one()
        assert ps.industry_tag == "medical"
        assert ps.sensitive_industry is True


async def test_start_modeling_non_sensitive_industry_flag_false(
    client, session_factory, seeded_common_fields
):
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t1", "profile": {"f_name": "耳机", "f_brief": "数码"}}
    )
    intake_id = r.json()["intake_id"]
    await _to_approved(client, intake_id)
    await _seed_industry_and_record(
        session_factory, intake_id=intake_id, industry="electronics", sensitive=False
    )

    assert (await _fire(client, intake_id, "start_modeling", actor=OPS)).status_code == 200

    from app.product.product_intake.models import ProductSpace

    async with session_factory() as session:
        ps = (
            await session.scalars(
                select(ProductSpace).where(ProductSpace.intake_id == intake_id)
            )
        ).one()
        assert ps.industry_tag == "electronics"
        assert ps.sensitive_industry is False


async def test_start_modeling_without_c1_record_keps_flags_neutral(
    client, session_factory, seeded_common_fields
):
    # 无 C1 识别记录的异常建模路径：不臆造行业，两列保持 NULL/false 默认。
    r = await client.post(
        "/api/intakes", json={"tenant_id": "t1", "profile": {"f_name": "未识别货", "f_brief": "x"}}
    )
    intake_id = r.json()["intake_id"]
    await _to_approved(client, intake_id)

    assert (await _fire(client, intake_id, "start_modeling", actor=OPS)).status_code == 200

    from app.product.product_intake.models import ProductSpace

    async with session_factory() as session:
        ps = (
            await session.scalars(
                select(ProductSpace).where(ProductSpace.intake_id == intake_id)
            )
        ).one()
        assert ps.industry_tag is None
        assert ps.sensitive_industry is False


# ---------- 评审 P1-1：录入单面凭证闸（零凭证 401 / 跨租户收口 / 自报身份作废） ----------


async def test_p11_no_token_all_intake_endpoints_401(client):
    """无令牌：列表/总览/创建/详情/迁移/改资料/事件/产品空间/目标语言一律 401。"""
    noauth = {"Authorization": ""}
    checks = [
        await client.get("/api/intakes", params={"tenant_id": "t1"}, headers=noauth),
        await client.get("/api/intakes/overview", params={"tenant_id": "t1"}, headers=noauth),
        await client.post(
            "/api/intakes",
            json={"tenant_id": "t1", "profile": {}},
            headers=noauth,
        ),
        await client.get("/api/intakes/any-id", headers=noauth),
        await client.post(
            "/api/intakes/any-id/transitions",
            json={"event": "submit", "actor": OPS},
            headers=noauth,
        ),
        await client.patch(
            "/api/intakes/any-id/profile",
            json={"profile": {}, "actor": CUSTOMER},
            headers=noauth,
        ),
        await client.get("/api/intakes/any-id/allowed-events", headers=noauth),
        await client.get("/api/intakes/any-id/product-space", headers=noauth),
        await client.patch(
            "/api/intakes/any-id/target-languages",
            params={"tenant_id": "t1"},
            json={"languages": [], "actor": CUSTOMER},
            headers=noauth,
        ),
    ]
    assert [r.status_code for r in checks] == [401] * len(checks)


async def test_p11_client_token_happy_path(client, seeded_common_fields):
    """客户令牌（绑定 t1）：建单→详情→迁移全通；身份取客户令牌而非 body 自报。"""
    secret = await issue_client_token(client, "t1", client_name="buyer-A")
    auth = client_bearer(secret)
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "面霜"}},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    intake_id = r.json()["intake_id"]
    assert (await client.get(f"/api/intakes/{intake_id}", headers=auth)).status_code == 200
    assert (
        await client.get("/api/intakes", params={"tenant_id": "t1"}, headers=auth)
    ).status_code == 200
    # 缺 f_brief 时 submit 被状态门拒（422 缺字段），证明请求已过凭证闸进入业务层
    missing = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "submit", "actor": CUSTOMER},
        headers=auth,
    )
    assert missing.status_code == 422
    await client.patch(
        f"/api/intakes/{intake_id}/profile",
        json={"profile": {"f_brief": "保湿"}, "actor": CUSTOMER},
        headers=auth,
    )
    ok = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "submit", "actor": CUSTOMER},
        headers=auth,
    )
    assert ok.status_code == 200, ok.text


async def test_p11_client_token_cannot_cross_tenant(client, session_factory):
    """t1 客户令牌：列 t2 → 401（依赖绑定）；读 t2 的单 → 404；替 t2 建单 → 401。"""
    async with session_factory() as session:
        session.add(Tenant(tenant_id="t2", name="隔壁", plan="basic", status="active"))
        await session.commit()
    # 用 staff 令牌替 t2 建一单（运营跨租户是设计内行为）
    r = await client.post("/api/intakes", json={"tenant_id": "t2", "profile": {}})
    t2_intake = r.json()["intake_id"]

    secret = await issue_client_token(client, "t1")
    auth = client_bearer(secret)
    assert (
        await client.get("/api/intakes", params={"tenant_id": "t2"}, headers=auth)
    ).status_code == 401
    assert (await client.get(f"/api/intakes/{t2_intake}", headers=auth)).status_code == 404
    assert (
        await client.post(
            "/api/intakes",
            json={"tenant_id": "t2", "profile": {}},
            headers=auth,
        )
    ).status_code == 401
    # 跨租户写：推 t2 单的状态机
    assert (
        await client.post(
            f"/api/intakes/{t2_intake}/transitions",
            json={"event": "submit", "actor": CUSTOMER},
            headers=auth,
        )
    ).status_code == 404


async def test_p11_client_token_cannot_self_declare_ops_role(client, seeded_common_fields):
    """客户令牌 + body 自报 operations 不能触发运营事件（身份以令牌验真为准）。

    ops_confirm 从 SUBMITTED 出发需要 operations（statemachine L66）；
    客户令牌的角色恒为 whitelist_owner，自报 roles 被忽略 → RoleRequired 403。
    """
    secret = await issue_client_token(client, "t1")
    auth = client_bearer(secret)
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "面霜", "f_brief": "x"}},
        headers=auth,
    )
    intake_id = r.json()["intake_id"]
    submitted = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "submit", "actor": CUSTOMER},
        headers=auth,
    )
    assert submitted.status_code == 200, submitted.text
    # submit → AI_RECOGNIZING；wf01_confirm（无角色门）→ PENDING_CONFIRM；
    # 自报 operations 打 ops_confirm → 客户令牌角色不含 operations → 403。
    confirmed = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "wf01_confirm", "actor": CUSTOMER},
        headers=auth,
    )
    assert confirmed.status_code == 200, confirmed.text
    r = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "ops_confirm", "actor": {"id": "cust", "roles": ["operations"]}},
        headers=auth,
    )
    assert r.status_code == 403, f"自报 operations 竟生效：{r.status_code} {r.text}"


async def test_p11_staff_token_without_ops_role_403(client):
    """staff 令牌但无 operations/platform_admin 角色 → 403（角色是硬闸）。"""
    weak = await issue_staff_token_limited(client)
    r = await client.get("/api/intakes", params={"tenant_id": "t1"}, headers=bearer(weak))
    assert r.status_code == 403


async def issue_staff_token_limited(client):
    """签一枚无运营角色的 staff 令牌（只在册人员，非 operations）。"""
    from tests.integration.staff_tokens import issue_staff_token

    return await issue_staff_token(client, ["product_reviewer"], staff_id="s-reviewer")
