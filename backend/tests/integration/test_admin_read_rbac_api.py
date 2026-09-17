"""Q109/Q113：管理端读端点鉴权审计后的同型补闸。

矩阵（docs/05 各行）把 GET 与写操作同组标注角色、而代码自 Q75 红线收口起
仅在写口挂角色闸的管理面 GET，统一补 query actor 依赖：
缺 actor_id → 422（FastAPI 必填 query），角色不符 → 403，命中 → 200。

Q109 首批 8 个读口；Q113 收口当时挂【原文未给出，待补】的三族 7 个读口
（config 三 GET = platform_admin 写口同组、g2-candidates = dictionary_admin
矩阵 05:98 GET/POST 同行、skill-prompts 三 GET = platform_admin 写口同组）。

矩阵明确「GET 无 actor 体」的读口保持开放（文件末尾锁定）：
ai-models/{id}/keys 与 agent-keys 为矩阵明确的无 actor 列表口径（只回元数据）。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app

# (path, 允许角色) ——与 docs/05 表行逐一对应。
GATED_READS = [
    ("/api/admin/c1/signal-weights", ["operations"]),           # 05:82  Q2
    ("/api/admin/c1/industries", ["operations"]),               # 05:83  Q7
    ("/api/categories", ["dictionary_admin"]),                  # 05:87  Q68
    ("/api/admin/fp-source-routes", ["operations"]),            # 05:94  Q8
    ("/api/admin/compliance-wordlist", ["operations", "internal_compliance"]),  # 05:104 Q48
    ("/api/admin/fit-weights", ["operations"]),                 # 05:155 Q34
    ("/api/admin/ai-models", ["platform_admin"]),               # 05:225 Q82
    ("/api/admin/ai-scene-routes", ["operations", "platform_admin"]),          # 05:230 Q82
    # ---- Q113：Q109 挂【待补】三族收口 ----
    ("/api/admin/config", ["platform_admin"]),                  # 05:177-179 写口同组
    ("/api/admin/g2-candidates", ["dictionary_admin"]),         # 05:98  GET/POST 同行 Q13/Q68
    ("/api/admin/skill-prompts", ["platform_admin"]),           # 05:233-234 写口同组 Q82-4
]

# Q113 子路径读口（资源可能不存在，故只锁鉴权层 422/403，不强制 200）。
GATED_SUBPATHS = [
    "/api/admin/config/some.key",
    "/api/admin/config/some.key/history",
    "/api/admin/skill-prompts/PWC-BUILDER/versions",
    "/api/admin/skill-prompts/PWC-BUILDER/versions/v0.1",
]

# 矩阵明确无 actor 体的读口：继续免闸。
OPEN_READS = [
    "/api/admin/agent-keys",
]


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
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.parametrize("path,_roles", GATED_READS)
async def test_admin_read_requires_actor_query(client, path, _roles):
    # 缺 actor_id → 422；给 actor 但 roles 为空 → 403。
    assert (await client.get(path)).status_code == 422
    denied = await client.get(path, params=[("actor_id", "cust-1"), ("roles", "customer")])
    assert denied.status_code == 403, (path, denied.status_code, denied.text)


@pytest.mark.parametrize("path,allowed_roles", GATED_READS)
async def test_admin_read_allows_matrix_roles(client, path, allowed_roles):
    for role in allowed_roles:
        resp = await client.get(path, params=[("actor_id", f"{role}-1"), ("roles", role)])
        assert resp.status_code == 200, (path, role, resp.status_code, resp.text)


async def test_wordlist_read_denies_roles_outside_matrix(client):
    # 词表读口仅 operations/internal_compliance：platform_admin/customer 均 403。
    for role in ("platform_admin", "product_reviewer"):
        resp = await client.get(
            "/api/admin/compliance-wordlist",
            params=[("actor_id", f"{role}-1"), ("roles", role)],
        )
        assert resp.status_code == 403, (role, resp.status_code, resp.text)
    internal = await client.get(
        "/api/admin/compliance-wordlist",
        params=[("actor_id", "ic-1"), ("roles", "internal_compliance")],
    )
    assert internal.status_code == 200


async def test_categories_read_denies_operations(client):
    # 字典读口归 dictionary_admin：operations 不在矩阵角色内。
    resp = await client.get(
        "/api/categories", params=[("actor_id", "ops-1"), ("roles", "operations")]
    )
    assert resp.status_code == 403


# ---- Q113：三族子路径同样先过鉴权依赖（资源存在与否不影响 422/403）----

@pytest.mark.parametrize("path", GATED_SUBPATHS)
async def test_q113_subpaths_require_actor_query(client, path):
    assert (await client.get(path)).status_code == 422
    denied = await client.get(path, params=[("actor_id", "cust-1"), ("roles", "customer")])
    assert denied.status_code == 403, (path, denied.status_code, denied.text)


async def test_q113_config_read_is_platform_admin_only(client):
    # 配置中心读口与写口同组：operations/customer 均 403。
    for role in ("operations", "customer", "dictionary_admin"):
        resp = await client.get(
            "/api/admin/config", params=[("actor_id", f"{role}-1"), ("roles", role)]
        )
        assert resp.status_code == 403, (role, resp.status_code, resp.text)


async def test_q113_g2_candidates_read_is_dictionary_admin_only(client):
    # G2 候选列表归 dictionary_admin（05:98）：operations/platform_admin 均 403。
    for role in ("operations", "platform_admin", "customer"):
        resp = await client.get(
            "/api/admin/g2-candidates",
            params=[("actor_id", f"{role}-1"), ("roles", role)],
        )
        assert resp.status_code == 403, (role, resp.status_code, resp.text)


async def test_q113_prompts_read_is_platform_admin_only(client):
    # Skill Prompt 读口与发布写口同组：operations/product_reviewer 均 403。
    for role in ("operations", "product_reviewer", "customer"):
        resp = await client.get(
            "/api/admin/skill-prompts",
            params=[("actor_id", f"{role}-1"), ("roles", role)],
        )
        assert resp.status_code == 403, (role, resp.status_code, resp.text)


@pytest.mark.parametrize("path", OPEN_READS)
async def test_matrix_open_reads_remain_actorless(client, path):
    # 无 actor query 即 200：锁定 Q109 审计的「有意开放/口径待补」结论。
    assert (await client.get(path)).status_code == 200, path


async def test_model_keys_list_remains_actorless(client):
    # outbound Key 列表（docs/05:228/234「同 outbound Key 列表口径」，仅元数据）：
    # 未知 model_id 可以 404，但绝不能因缺 actor 返 422/403。
    resp = await client.get("/api/admin/ai-models/m-unknown/keys")
    assert resp.status_code not in (403, 422), resp.status_code
