"""Q109/Q113：管理端读端点鉴权审计后的同型补闸。

矩阵（docs/05 各行）把 GET 与写操作同组标注角色、而代码自 Q75 红线收口起
仅在写口挂角色闸的管理面 GET，统一补 query actor 依赖：
缺 actor_id → 422（FastAPI 必填 query），角色不符 → 403，命中 → 200。

Q109 首批 8 个读口；Q113 收口当时挂【原文未给出，待补】的三族 7 个读口
（config 三 GET = platform_admin 写口同组、g2-candidates = dictionary_admin
矩阵 05:98 GET/POST 同行、skill-prompts 三 GET = platform_admin 写口同组）。
Q118 补 Q117 审计发现 Q109 穷举清单遗漏的 4 个读口（content-goals =
dictionary_admin、cp-law-domains = internal_compliance、publish-slots /
slot-type-defaults = operations）。

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
from scripts.route_auth_matrix import collect

# (path, 允许角色) ——与 docs/05 表行逐一对应。
GATED_READS = [
    ("/api/admin/c1/signal-weights", ["operations"]),           # 05:82  Q2
    ("/api/admin/c1/industries", ["operations"]),               # 05:83  Q7
    ("/api/categories", ["dictionary_admin"]),                  # 05:87  Q68
    ("/api/admin/fp-source-routes", ["operations"]),            # 05:94  Q8
    ("/api/admin/compliance-wordlist", ["operations", "internal_compliance"]),  # 05:104 Q48
    ("/api/admin/fit-weights", ["operations", "platform_admin"]),  # 05:155 Q34／Q346 甲读面统一
    ("/api/admin/ai-models", ["platform_admin"]),               # 05:225 Q82
    ("/api/admin/ai-scene-routes", ["operations", "platform_admin"]),          # 05:230 Q82
    # ---- Q113：Q109 挂【待补】三族收口 ----
    ("/api/admin/config", ["platform_admin"]),                  # 05:177-179 写口同组
    ("/api/admin/g2-candidates", ["dictionary_admin"]),         # 05:98  GET/POST 同行 Q13/Q68
    ("/api/admin/skill-prompts", ["platform_admin"]),           # 05:233-234 写口同组 Q82-4
    # ---- Q118：Q117 审计发现 Q109 穷举遗漏的 4 个 ----
    # Q307 放行 platform_admin；Q350（清单二 #12 甲）再放行 operations，与段7/8 一条读闸
    ("/api/admin/content-goals", ["dictionary_admin", "platform_admin", "operations"]),   # 05 Q25 字典／Q307/Q350 读面
    ("/api/admin/cp-law-domains", ["internal_compliance"]),    # 05 Q49 敏感领域清单
    # ---- Q346（负责人「按你推荐的搞」裁甲，02 C1.289）：段7/8 管理端读口统一到一条闸 ----
    # 五张原只认 operations 的读口改挂 `require_ops_admin_view`（管理端 `/admin/platform-adaptation`
    # 建成屏后要读它们），四张原本连 query 读闸都没有的（platform-rules／match／pcp-templates／
    # fit-score，Q345 真进程实测零身份即 200）补同一条闸。**写口一律未动**，仍只认已验真 staff 令牌。
    ("/api/admin/publish-slots", ["operations", "platform_admin"]),  # 05 Q35 发布位档案／Q307 读面
    ("/api/admin/slot-type-defaults", ["operations", "platform_admin"]),  # 05 Q39 slotType 默认值
    ("/api/admin/platform-rules", ["operations", "platform_admin"]),  # 05 Q36 平台规则
    ("/api/admin/pcp-templates", ["operations", "platform_admin"]),  # 05 Q39 四模板只读
    ("/api/admin/platform-dynamic-events", ["operations", "platform_admin"]),  # 05 Q37 动态信号
    ("/api/admin/pcp-recalc/candidates", ["operations", "platform_admin"]),  # 05 Q41/Q42 重算候选
    ("/api/admin/platform-adapter/candidates", ["operations", "platform_admin"]),  # 05 Q300 adapter 候选
    # ---- Q262：layerSpaces 通用底座读口（Q46 普通运营只读，platform_admin 可读） ----
    ("/api/admin/layer-spaces", ["operations", "platform_admin"]),  # 02 Q46
    # ---- Q264：三包重配待办清单只读口（Q45 重配走 Gate，operations|platform_admin 只读） ----
    ("/api/admin/packages/reuse-pending", ["operations", "platform_admin"]),  # 02 Q264
]

# Q113 子路径读口（资源可能不存在，故只锁鉴权层 422/403，不强制 200）。
GATED_SUBPATHS = [
    "/api/admin/config/some.key",
    "/api/admin/config/some.key/history",
    "/api/admin/skill-prompts/PWC-BUILDER/versions",
    "/api/admin/skill-prompts/PWC-BUILDER/versions/v0.1",
    "/api/admin/layer-spaces/items/some.item/impact",
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


# ---- Q118：漏网 4 读口的角色边界 ----

async def test_q307_content_goals_read_matrix_and_the_untouched_write(client):
    """Q118 原判据是"只认 dictionary_admin"；Q307 按甲把**读**面放行 platform_admin；
    Q350（清单二 #12 甲）再放行 operations，与段7/8 读闸统一。

    改的是已裁的东西，所以这里把新边界钉牢：customer 仍在读面被拒；
    operations／dictionary_admin／platform_admin 可读；写口 upsert 仍只认 dictionary_admin——
    读面放宽不等于写面放宽，这条断言就是那道口子的封条。
    """
    for role in ("customer",):
        resp = await client.get(
            "/api/admin/content-goals",
            params=[("actor_id", f"{role}-1"), ("roles", role)],
        )
        assert resp.status_code == 403, (role, resp.status_code, resp.text)
    for role in ("dictionary_admin", "platform_admin", "operations"):
        ok = await client.get(
            "/api/admin/content-goals",
            params=[("actor_id", f"{role}-1"), ("roles", role)],
        )
        assert ok.status_code == 200, (role, ok.status_code, ok.text)

    # 写口一口未动：goal 的 upsert 走 service 层 dictionary_admin 闸，platform_admin 不行。
    refused = await client.put(
        "/api/admin/content-goals",
        json={"code": "ENGAGEMENT", "color": "#111", "ratio_min": 0.1, "ratio_max": 0.2,
              "actor": {"id": "pa-1", "roles": ["platform_admin"]}},
    )
    assert refused.status_code == 403, refused.text


async def test_q118_law_domains_read_is_internal_compliance_only(client):
    # CP-LAW 敏感领域读口：operations/platform_admin/customer 均 403。
    for role in ("operations", "platform_admin", "customer"):
        resp = await client.get(
            "/api/admin/cp-law-domains",
            params=[("actor_id", f"{role}-1"), ("roles", role)],
        )
        assert resp.status_code == 403, (role, resp.status_code, resp.text)
    ok = await client.get(
        "/api/admin/cp-law-domains",
        params=[("actor_id", "ic-1"), ("roles", "internal_compliance")],
    )
    assert ok.status_code == 200


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


# ---- Q346（负责人「按你推荐的搞」裁甲，02 C1.289）：段7/8 管理端读口收到同一条闸 ----


def _stage78_admin_gets() -> list[str]:
    """反向枚举这一族的全部管理端 GET（不手抄清单，照 Q277 `GATED` 同型纪律）。"""
    return sorted(
        {
            r.path
            for r in collect(app.routes, [])
            if "GET" in r.methods
            and r.path.startswith("/api/admin")
            and "platform_adaptation" in getattr(r.endpoint, "__module__", "")
        }
    )


def test_the_stage78_family_has_exactly_ten_admin_reads() -> None:
    """成员数钉死＝新增一条管理端 GET 却没挂读闸时，这条先红，而不是静默多一个免闸口。"""
    paths = _stage78_admin_gets()
    assert len(paths) == 10, paths


@pytest.mark.parametrize("path", _stage78_admin_gets())
async def test_every_stage78_admin_read_reaches_the_gate(client, path):
    """九张读口（含带必填业务参数的 match／fit-score）都必须先答鉴权、再答参数。

    实测 FastAPI 先求解依赖，所以角色不符时即便缺 `platform`／`goal` 也回 **403**——
    这条探针因此不需要为每条口手写业务参数，又能保证"漏挂读闸必判红"。
    缺 actor_id 那条只作弱判据（match／fit-score 缺业务参数同样是 422，码不可分），
    承重的是上面那条 403。
    """
    denied = await client.get(path, params=[("actor_id", "nobody-1"), ("roles", "nobody")])
    assert denied.status_code == 403, (path, denied.status_code, denied.text)
    assert (await client.get(path)).status_code == 422, path


async def test_q346_match_and_fit_score_pass_the_gate_for_both_admin_roles(client):
    """正向对照：放行之后才轮到业务层（空库下 match 回 native、未知 slot 回 404）。"""
    probes = [
        ("/api/admin/platform-rules/match", [("platform", "xhs"), ("slot_type", "note")]),
        ("/api/admin/publish-slots/slot-q346/fit-score", [("goal", "ENGAGEMENT")]),
    ]
    for path, business in probes:
        for role in ("operations", "platform_admin"):
            resp = await client.get(
                path, params=[("actor_id", f"{role}-1"), ("roles", role), *business]
            )
            assert resp.status_code not in (401, 403, 422), (
                path,
                role,
                resp.status_code,
                resp.text,
            )


@pytest.mark.parametrize("path", OPEN_READS)
async def test_matrix_open_reads_remain_actorless(client, path):    # 无 actor query 即 200：锁定 Q109 审计的「有意开放/口径待补」结论。
    assert (await client.get(path)).status_code == 200, path


async def test_model_keys_list_remains_actorless(client):
    # outbound Key 列表（docs/05:228/234「同 outbound Key 列表口径」，仅元数据）：
    # 未知 model_id 可以 404，但绝不能因缺 actor 返 422/403。
    resp = await client.get("/api/admin/ai-models/m-unknown/keys")
    assert resp.status_code not in (403, 422), resp.status_code
