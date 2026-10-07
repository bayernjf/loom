"""Q38 降级动作字典管理面集成测试（载体随 Q306 落）。

钉三件与旧字典族不同的事：
- 写口走 Q203/Q242 现行凭证标准——**门控关着也自行验真**，无令牌 401、角色不足 403，
  不再复制 content_goals／content_languages 的 body 自报角色；
- 审计里的人员是被凭证派生的，不是正文里写谁就是谁；
- 软归档＋显式 upsert 复活与同族字典同口径。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.downgrade_actions.models import DowngradeAction
from app.core.downgrade_actions.seeds import DOWNGRADE_ACTION_CODES
from app.core.models import AuditLog
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from tests.integration.staff_tokens import acting_as, bearer, issue_staff_token

DICT_ROLES = ["dictionary_admin"]


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
        for code in DOWNGRADE_ACTION_CODES:
            session.add(DowngradeAction(code=code))
        await session.commit()


async def _audits(factory, action: str) -> list[AuditLog]:
    async with factory() as session:
        return list(
            (
                await session.scalars(select(AuditLog).where(AuditLog.action == action))
            ).all()
        )


VIEW = {"actor_id": "ops-1", "roles": ["operations"]}


async def test_get_needs_a_query_actor_and_only_the_dictionary_family_may_read(
    client, session_factory
) -> None:
    await _seed(session_factory)

    missing = await client.get("/api/admin/downgrade-actions")
    assert missing.status_code == 422, missing.text

    wrong = await client.get(
        "/api/admin/downgrade-actions", params={"actor_id": "x", "roles": ["content_writer"]}
    )
    assert wrong.status_code == 403, wrong.text

    ok = await client.get("/api/admin/downgrade-actions", params=VIEW)
    assert ok.status_code == 200, ok.text
    # 读口按 code 排序返回，与种子的书写顺序无关
    assert [r["code"] for r in ok.json()] == sorted(DOWNGRADE_ACTION_CODES)


async def test_write_ports_refuse_anonymous_and_wrong_role_even_with_gate_off(
    client, session_factory
) -> None:
    """门控默认关（settings.staff_auth_enabled=False）——require_internal_actor 仍自行验真。"""
    saved = client.headers.pop("Authorization")
    anon = await client.put("/api/admin/downgrade-actions", json={"code": "NEW_ACTION"})
    client.headers.update({"Authorization": saved})
    assert anon.status_code == 401, anon.text

    async with acting_as(client, ["operations"], staff_id="s-ops-only"):
        refused = await client.put("/api/admin/downgrade-actions", json={"code": "NEW_ACTION"})
    assert refused.status_code == 403, refused.text


async def test_upsert_normalises_the_code_and_writes_the_row(client, session_factory) -> None:
    resp = await client.put(
        "/api/admin/downgrade-actions",
        json={"code": "remove_brand", "name": "去品牌", "why": "平台禁硬广"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == "REMOVE_BRAND"  # 码归一化为大写枚举码

    rows = await client.get("/api/admin/downgrade-actions", params=VIEW)
    stored = next(r for r in rows.json() if r["code"] == "REMOVE_BRAND")
    assert stored["name"] == "去品牌" and stored["why"] == "平台禁硬广"
    async with session_factory() as session:
        assert await session.get(DowngradeAction, "REMOVE_BRAND") is not None
        # 主键存的是归一码，小写那份不该另外存在
        assert await session.get(DowngradeAction, "remove_brand") is None


async def test_audit_actor_is_server_derived_not_self_declared(client, session_factory) -> None:
    """正文里写谁都无效：审计的 actor_id 必须是令牌背后那个人（Q192/Q203 口径）。"""
    await client.put(
        "/api/admin/downgrade-actions",
        json={"code": "SHORTEN", "name": "缩短", "why": "超长降级", "actor": {"id": "nobody"}},
    )
    rows = await _audits(session_factory, "downgrade_action.upsert")
    assert len(rows) == 1
    assert rows[0].entity_id == "SHORTEN"
    assert rows[0].actor_id == "s-dict"  # 令牌签发的 staff_id，不是正文里的 nobody
    assert rows[0].detail["_actor_via"] == "staff_token"  # 身份来源标明是凭证派生


async def test_bad_code_is_rejected_with_422(client) -> None:
    resp = await client.put("/api/admin/downgrade-actions", json={"code": "  "})
    assert resp.status_code == 422, resp.text


async def test_archive_is_soft_and_upsert_revives(client, session_factory) -> None:
    await _seed(session_factory)

    unknown = await client.post("/api/admin/downgrade-actions/NOPE/archive")
    assert unknown.status_code == 404, unknown.text

    gone = await client.post("/api/admin/downgrade-actions/SOFT_CTA/archive")
    assert gone.status_code == 200, gone.text
    assert gone.json()["status"] == "archived"

    active = await client.get("/api/admin/downgrade-actions", params=VIEW)
    assert "SOFT_CTA" not in [r["code"] for r in active.json()]
    everything = await client.get(
        "/api/admin/downgrade-actions", params={**VIEW, "include_archived": "true"}
    )
    assert "SOFT_CTA" in [r["code"] for r in everything.json()]

    revived = await client.put("/api/admin/downgrade-actions", json={"code": "SOFT_CTA"})
    assert revived.status_code == 200, revived.text
    assert revived.json()["status"] == "active"

    rows = await _audits(session_factory, "downgrade_action.archive")
    assert [r.entity_id for r in rows] == ["SOFT_CTA"]


@pytest.mark.parametrize("code", DOWNGRADE_ACTION_CODES)
def test_the_six_codes_are_exactly_the_words_in_the_ruling(code: str) -> None:
    """docs/02:141 用户原话列的六项＝种子事实源；改名/漏项都在这里判红。"""
    assert code in {
        "REMOVE_BRAND",
        "REMOVE_CLAIM",
        "REMOVE_LINK",
        "SOFT_CTA",
        "SHORTEN",
        "SUBST_WORD",
    }
