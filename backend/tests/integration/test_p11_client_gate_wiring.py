"""评审 P1-1（2026-11-02）结构用例：intakes/effects/exports 客户面与中台面的闸型登记。

行为用例（401/403/404）只能证明"现在过不去"，定位不到是 `Depends` 被摘了；
本文件按路由点名凭证标记（`loom_requires_client_credential` /
`loom_requires_agent_credential`），少一个标记即判红。路由面变化（新增/删除
端点、换闸型）必须先改这里——这是防回归的登记处，不是文档。
"""

from fastapi.routing import APIRoute

from app.main import app

CLIENT_MARKER = "loom_requires_client_credential"
AGENT_MARKER = "loom_requires_agent_credential"

# 客户/运营双闸或客户令牌闸（intakes 除 ops-queue 外的全表面 + effects 回填/分析）。
# ops-queue 是 query-actor 读闸（Q107 既定契约），不在本表。
CLIENT_GATED = {
    ("GET", "/api/intakes"),
    ("GET", "/api/intakes/overview"),
    ("POST", "/api/intakes"),
    ("GET", "/api/intakes/{intake_id}"),
    ("PATCH", "/api/intakes/{intake_id}/profile"),
    ("GET", "/api/intakes/{intake_id}/allowed-events"),
    ("POST", "/api/intakes/{intake_id}/transitions"),
    ("GET", "/api/intakes/{intake_id}/product-space"),
    ("PATCH", "/api/intakes/{intake_id}/target-languages"),
    ("POST", "/api/effects/backfill"),
    ("POST", "/api/effects/backfill/upload"),
    ("POST", "/api/effects/backfill/upload-excel"),
    ("GET", "/api/effects/analytics"),
}

# 中台导出面：Agent Key 机器凭证（Q88 族）。
AGENT_GATED = {
    ("GET", "/api/exports/fcw.csv"),
    ("GET", "/api/exports/fcw.json"),
    ("POST", "/api/exports/jobs"),
    ("GET", "/api/exports/jobs"),
    ("GET", "/api/exports/jobs/{job_id}"),
    ("GET", "/api/exports/jobs/{job_id}/download"),
}


def _routes() -> dict[tuple[str, str], APIRoute]:
    routes: dict[tuple[str, str], APIRoute] = {}
    stack = list(app.routes)
    while stack:
        node = stack.pop()
        if isinstance(node, APIRoute):
            for verb in node.methods or set():
                if verb.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                    routes[(verb.upper(), node.path)] = node
            continue
        inner = getattr(node, "routes", None) or getattr(
            getattr(node, "original_router", None), "routes", None
        )
        if inner:
            stack.extend(inner)
    return routes


def _markers(route: APIRoute) -> set[str]:
    out: set[str] = set()
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        for marker in (CLIENT_MARKER, AGENT_MARKER):
            if getattr(call, marker, False):
                out.add(marker)
        stack.extend(getattr(dep, "dependencies", []) or [])
    return out


def test_client_gated_routes_carry_the_marker() -> None:
    routes = _routes()
    missing = [
        f"{m} {p}" for m, p in sorted(CLIENT_GATED)
        if (m, p) not in routes or CLIENT_MARKER not in _markers(routes[(m, p)])
    ]
    assert not missing, f"客户闸被摘或路由消失：{missing}"


def test_agent_gated_routes_carry_the_marker() -> None:
    routes = _routes()
    missing = [
        f"{m} {p}" for m, p in sorted(AGENT_GATED)
        if (m, p) not in routes or AGENT_MARKER not in _markers(routes[(m, p)])
    ]
    assert not missing, f"Agent Key 闸被摘或路由消失：{missing}"


def test_gate_registries_stay_disjoint_and_ops_queue_keeps_its_own_gate() -> None:
    assert not (CLIENT_GATED & AGENT_GATED)
    routes = _routes()
    ops_queue = routes[("GET", "/api/intakes/ops-queue")]
    # Q107 读闸是 query-actor 而非凭证依赖：本表不管它，但也绝不允许给它挂凭证标记
    # 冒充"已收口"（它由 staff 门控与 require_ops_view 覆盖）。
    assert _markers(ops_queue) == set()
