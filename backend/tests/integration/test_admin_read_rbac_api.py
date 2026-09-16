"""Q109：管理端读端点鉴权审计后的同型补闸。

矩阵（docs/05 各行）把 GET 与写操作同组标注角色、而代码自 Q75 红线收口起
仅在写口挂角色闸的 8 个管理面 GET，本切片统一补 query actor 依赖：
缺 actor_id → 422（FastAPI 必填 query），角色不符 → 403，命中 → 200。

矩阵未定读角色或矩阵明确「GET 无 actor 体」的读口保持开放（文件末尾锁定）：
config 三 GET、g2-candidates、skill-prompts 三 GET 读角色【原文未给出，待补】；
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
]

# 矩阵未定读角色（【原文未给出，待补】）或明确无 actor 体的读口：继续免闸。
OPEN_READS = [
    "/api/admin/config",
    "/api/admin/g2-candidates",
    "/api/admin/skill-prompts",
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


@pytest.mark.parametrize("path", OPEN_READS)
async def test_matrix_open_reads_remain_actorless(client, path):
    # 无 actor query 即 200：锁定 Q109 审计的「有意开放/口径待补」结论。
    assert (await client.get(path)).status_code == 200, path


async def test_model_keys_list_remains_actorless(client):
    # outbound Key 列表（docs/05:228/234「同 outbound Key 列表口径」，仅元数据）：
    # 未知 model_id 可以 404，但绝不能因缺 actor 返 422/403。
    resp = await client.get("/api/admin/ai-models/m-unknown/keys")
    assert resp.status_code not in (403, 422), resp.status_code
