"""管理端可读性契约（Q307）：前端管理面要读的每个 GET，默认管理身份必须读得动。

来历＝Q306 落字典时实测查出：组装工作台首屏 `Promise.all([getAdminPublishSlots(),
getAdminContentGoals()])` 在官方 compose 形态（`LOOM_ADMIN_ROLES` 默认只有
platform_admin）下整体失败——不是"某个口慢"，是一屏打不开。这类缺陷 CI 六道门
全看不见：它不在代码里，在「能力」与「可达面」的差集里。

判据取前端自己的调用清单（`ADMIN_ROLE_LIST` 参与的那批 GET），逐个用
**只带 platform_admin 的身份**打一遍：403/404 之外都算通（404＝行不存在，不是身份问题）。
两条反向对照防门自己退化：清单必须非空，且每条路径必须解析到真实路由。
"""

import asyncio
import pathlib
import re

import pytest
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from scripts.route_auth_matrix import collect

API_TS = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "lib" / "api.ts"

# 管理端唯一保证存在的身份：compose 里 LOOM_ADMIN_ROLES 的默认值
DEFAULT_ADMIN_ROLES = ["platform_admin"]


def _admin_surface_get_paths() -> set[str]:
    """从 lib/api.ts 里取出「用 ADMIN_ROLE_LIST 自报身份发起的 GET」的路径清单。"""
    src = API_TS.read_text(encoding="utf-8")
    found: set[str] = set()
    for block in re.split(r"\n(?=export async function )", src):
        head = re.match(r"export async function (\w+)", block)
        if not head or "ADMIN_ROLE_LIST" not in block:
            continue
        call = re.search(
            r"request(?:<[^>]*>)?\(\s*[`\"']([^`\"'$]+)[^`\"']*[`\"']"
            r"(?:(?!request).)*?(method:\s*\"(\w+)\")?",
            block,
            re.DOTALL,
        )
        if not call:
            continue
        verb = re.search(r'method:\s*"(\w+)"', block.split(call.group(1))[1][:400])
        if verb and verb.group(1) != "GET":
            continue
        path = call.group(1).split("?")[0].rstrip("/") or "/"
        found.add(path)
    return found


def _routes_for(prefix: str) -> list[APIRoute]:
    """把前端写的路径对上后端真实路由（含带路径参数的形态）。"""
    routes = collect(app.routes, [])
    hits = []
    for r in routes:
        if "GET" not in r.methods or not r.path.startswith("/api"):
            continue
        concrete = re.sub(r"\{\w+(?::[^}]*)?\}", "probe", r.path)
        if concrete.rstrip("/") == prefix or (
            "{" in r.path and r.path.split("{")[0].rstrip("/").rstrip("/") == prefix
        ):
            hits.append((r, concrete))
    return hits


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


def _probe(paths: list[str]) -> dict[str, tuple[int, str]]:
    async def run() -> dict[str, tuple[int, str]]:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async def get_test_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = get_test_session
        from httpx import ASGITransport, AsyncClient

        out: dict[str, tuple[int, str]] = {}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            for path in paths:
                query = [("actor_id", "admin-probe")] + [
                    ("roles", role) for role in DEFAULT_ADMIN_ROLES
                ]
                resp = await ac.get(path, params=query)
                out[path] = (resp.status_code, resp.text[:160])
        app.dependency_overrides.clear()
        await engine.dispose()
        return out

    return asyncio.run(run())


def test_the_frontend_really_has_an_admin_read_surface() -> None:
    """反向对照：清单为空＝解析器失效＝下面那条门变空转。"""
    paths = _admin_surface_get_paths()
    assert paths, "lib/api.ts 里没解析到任何管理端 GET——解析式该修，不是门该撤"
    assert len(paths) >= 8, sorted(paths)


def test_every_admin_surface_read_resolves_to_a_real_route() -> None:
    for path in sorted(_admin_surface_get_paths()):
        assert _routes_for(path), f"前端在读 {path}，后端没有对应 GET 路由"


# 已裁授权口径把默认管理身份挡在外面的读口：不是漏网，是**已裁的接缝**，
# 放宽它需要重新裁决，故本门把它们排除在"必须可读"之外、同时钉死这个集合不许长大。
# /api/review-workbench/candidates ＝ 接缝③（Q232，负责人 2026-10-01 追认，02 C1.176）：
# platform_admin 不是队列角色，读队列也不放行。本批试过放宽，被
# tests/integration/test_review_workbench_api.py::test_queue_requires_actor_and_any_wf_gate_role
# 当场判红 ⇒ 收回，改登记 docs/19 清单二第 8 项待裁。
RATIFIED_SEAM_BLOCKED = {"/api/review-workbench/candidates"}


def test_platform_admin_can_read_every_admin_surface_endpoint() -> None:
    targets = sorted({c for path in _admin_surface_get_paths() for _, c in _routes_for(path)})
    results = _probe(targets)
    refused = {
        path
        for path, (code, _) in results.items()
        if code in (401, 403)
    }
    new_holes = refused - RATIFIED_SEAM_BLOCKED
    assert not new_holes, "管理端读口把默认身份挡在外面：" + ", ".join(
        f"{p}→{results[p][0]}" for p in sorted(new_holes)
    )


def test_the_ratified_seam_exception_cannot_silently_grow() -> None:
    """例外必须是"确实存在、确实被前端读、确实仍 403"的口——不许拿它当后门。"""
    paths = _admin_surface_get_paths()
    assert RATIFIED_SEAM_BLOCKED <= paths, sorted(RATIFIED_SEAM_BLOCKED - paths)
    targets = sorted({c for path in RATIFIED_SEAM_BLOCKED for _, c in _routes_for(path)})
    assert targets, "例外清单里的路径没解析到真实路由"
    for path, (code, _) in _probe(targets).items():
        assert code == 403, f"{path} 现在回 {code}——接缝③ 已被改动，这条例外该删或该改判"

