"""Q43 17 池选项字典管理面集成测试（载体随 Q308 落）。

与 Q306 降级动作字典同族，但这里多钉两件本表特有的事：
- **池名是闭合集**：17 个键由 Q40 权重校验器认的那份定义（`pa_rules.WEIGHT_KEYS_17`）
  决定，字典不能自己长出第 18 个池，未知池 422；
- **选项只校形状不校语义**：原文未给任何一池的候选值，所以能清空、能回填，
  但空串／重复／非字符串必须挡在写口。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.pool_options.models import PoolOption
from app.core.pool_options.seeds import POOL_KEYS
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from app.platform.platform_adaptation.pa_rules import WEIGHT_KEYS_17
from tests.integration.staff_tokens import acting_as, bearer, issue_staff_token

DICT_ROLES = ["dictionary_admin"]
VIEW = {"actor_id": "ops-1", "roles": ["operations"]}


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
    """默认带一枚 dictionary_admin 令牌；负向用例用 acting_as 临时换角色。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        secret = await issue_staff_token(ac, DICT_ROLES, staff_id="s-dict")
        ac.headers.update(bearer(secret))
        yield ac


async def _seed(factory) -> None:
    async with factory() as session:
        for pool in POOL_KEYS:
            session.add(PoolOption(pool=pool, options=[]))
        await session.commit()


async def _audits(factory, action: str) -> list[AuditLog]:
    async with factory() as session:
        return list(
            (await session.scalars(select(AuditLog).where(AuditLog.action == action))).all()
        )


async def test_get_needs_a_query_actor_and_the_admin_identity_can_read(
    client, session_factory
) -> None:
    await _seed(session_factory)

    missing = await client.get("/api/admin/pool-options")
    assert missing.status_code == 422, missing.text

    wrong = await client.get(
        "/api/admin/pool-options", params={"actor_id": "x", "roles": ["content_writer"]}
    )
    assert wrong.status_code == 403, wrong.text

    # Q307 规矩：管理端唯一保证存在的身份是 platform_admin，读口放行否则这一屏打开即 403
    admin = await client.get(
        "/api/admin/pool-options",
        params={"actor_id": "pa-1", "roles": ["platform_admin"]},
    )
    assert admin.status_code == 200, admin.text
    assert len(admin.json()) == 17

    ok = await client.get("/api/admin/pool-options", params=VIEW)
    assert ok.status_code == 200, ok.text
    # 读口按池名排序返回，与种子的书写顺序无关
    assert [r["pool"] for r in ok.json()] == sorted(POOL_KEYS)


async def test_write_ports_refuse_anonymous_and_wrong_role_even_with_gate_off(
    client, session_factory
) -> None:
    """门控默认关（settings.staff_auth_enabled=False）——require_internal_actor 仍自行验真。"""
    await _seed(session_factory)
    saved = client.headers.pop("Authorization")
    anon = await client.put("/api/admin/pool-options", json={"pool": "goal", "options": ["a"]})
    client.headers.update({"Authorization": saved})
    assert anon.status_code == 401, anon.text

    async with acting_as(client, ["operations"], staff_id="s-ops-only"):
        refused = await client.put(
            "/api/admin/pool-options", json={"pool": "goal", "options": ["a"]}
        )
    assert refused.status_code == 403, refused.text
    # 越权写在服务层就抛，未落库、未写审计
    assert await _audits(session_factory, "pool_option.upsert") == []


async def test_unknown_pool_is_rejected_because_the_seventeen_are_a_closed_set(
    client, session_factory
) -> None:
    await _seed(session_factory)
    resp = await client.put("/api/admin/pool-options", json={"pool": "eighteen", "options": ["x"]})
    assert resp.status_code == 422, resp.text
    assert "unknown pool" in resp.text
    assert await _audits(session_factory, "pool_option.upsert") == []


async def test_option_shape_is_enforced_but_semantics_are_not(client, session_factory) -> None:
    """空串／重复／非字符串挡在写口；选项内容本身不由工程侧认定。"""
    await _seed(session_factory)

    blank = await client.put("/api/admin/pool-options", json={"pool": "goal", "options": ["  "]})
    assert blank.status_code == 422, blank.text

    dup = await client.put(
        "/api/admin/pool-options", json={"pool": "goal", "options": ["硬广", "硬广"]}
    )
    assert dup.status_code == 422, dup.text
    assert "duplicate" in dup.text

    non_str = await client.put(
        "/api/admin/pool-options", json={"pool": "goal", "options": [123]}
    )
    assert non_str.status_code == 422, non_str.text

    # 形状合法即可回填——工程侧不校验"硬广"是不是一个该存在的选项值
    filled = await client.put(
        "/api/admin/pool-options", json={"pool": "goal", "options": ["硬广", "种草"]}
    )
    assert filled.status_code == 200, filled.text
    assert filled.json()["options"] == ["硬广", "种草"]
    assert filled.json()["updated_by"] == "s-dict"


async def test_upsert_normalises_the_pool_name_and_can_clear_a_pool(
    client, session_factory
) -> None:
    await _seed(session_factory)
    resp = await client.put("/api/admin/pool-options", json={"pool": "  GOAL  "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["pool"] == "goal"  # 池名归一为小写，与 WEIGHT_KEYS_17 同形

    async with session_factory() as session:
        assert await session.get(PoolOption, "goal") is not None
        assert await session.get(PoolOption, "GOAL") is None

    # 不传 options ＝清空该池可选集（回填前的默认形态）
    assert resp.json()["options"] == []


async def test_audit_actor_is_server_derived_not_self_declared(client, session_factory) -> None:
    """正文里写谁都无效：审计的 actor_id 必须是令牌背后那个人（Q192/Q203 口径）。"""
    await _seed(session_factory)
    await client.put(
        "/api/admin/pool-options",
        json={"pool": "tone", "options": ["口语"], "actor": {"id": "nobody"}},
    )
    rows = await _audits(session_factory, "pool_option.upsert")
    assert len(rows) == 1
    assert rows[0].entity_id == "tone"
    assert rows[0].actor_id == "s-dict"  # 令牌签发的 staff_id，不是正文里的 nobody
    assert rows[0].detail["_actor_via"] == "staff_token"
    assert rows[0].detail["count"] == 1


async def test_archive_is_soft_and_upsert_revives(client, session_factory) -> None:
    await _seed(session_factory)

    unknown = await client.post("/api/admin/pool-options/nope/archive")
    assert unknown.status_code == 404, unknown.text

    gone = await client.post("/api/admin/pool-options/hook/archive")
    assert gone.status_code == 200, gone.text
    assert gone.json()["status"] == "archived"

    active = await client.get("/api/admin/pool-options", params=VIEW)
    assert "hook" not in [r["pool"] for r in active.json()]
    assert len(active.json()) == 16
    everything = await client.get(
        "/api/admin/pool-options", params={**VIEW, "include_archived": "true"}
    )
    assert len(everything.json()) == 17

    revived = await client.put("/api/admin/pool-options", json={"pool": "hook", "options": ["提问"]})
    assert revived.status_code == 200, revived.text
    assert revived.json()["status"] == "active"

    rows = await _audits(session_factory, "pool_option.archive")
    assert [r.entity_id for r in rows] == ["hook"]


def test_the_dictionary_pool_set_is_the_one_the_weight_validator_enforces() -> None:
    """字典与 Q40 校验器必须是同一份 17 池定义；任一侧改名/增删都在这里判红。"""
    assert POOL_KEYS == WEIGHT_KEYS_17
    assert len(POOL_KEYS) == 17
    assert len(set(POOL_KEYS)) == 17
