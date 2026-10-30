"""P0 结构用例：content 路由全部端点必须挂已验真凭证依赖（防漏网，2026-10-30）。

行为用例只会说「200 不是 401」，定位不到是接线掉了；本用例遍历 app 路由表，
按依赖链上的接线标记（``loom_requires_client_credential`` /
``loom_requires_internal_credential``）逐条点名。同时断言路由面＝已知集合：
新增 content 端点必须先选闸（客户令牌 / staff 硬闸 / 管理面 query-actor 读闸）
并在此登记，否则判红——这是评审 P0「14 个无鉴权端点」的回归防线。
"""

from fastapi.routing import APIRoute

from app.main import app

CLIENT_MARKER = "loom_requires_client_credential"
INTERNAL_MARKER = "loom_requires_internal_credential"

# 客户口：客户访问令牌（loom_client_）。租户作用域端点令牌↔tenant 绑定一致；
# 语言目录为非租户作用域只读，仅验身份。
CLIENT_GATED = {
    ("POST", "/api/content/{content_id}/approve"),
    ("POST", "/api/content/{content_id}/reject"),
    ("POST", "/api/content/{content_id}/revise"),
    ("PATCH", "/api/content/{content_id}/body"),
    ("GET", "/api/content"),
    ("GET", "/api/content/{content_id}"),
    ("GET", "/api/content/languages"),
}

# 运营口：staff 个人令牌硬闸（require_internal_actor，无令牌一律 401）。
STAFF_GATED = {
    ("POST", "/api/content/generate"),
    ("POST", "/api/content/{content_id}/regenerate"),
    ("POST", "/api/content/{content_id}/discard"),
    ("PUT", "/api/admin/content/{content_id}/publish-info"),
    ("PUT", "/api/admin/content-languages"),
    ("POST", "/api/admin/content-languages/{code}/archive"),
    ("PUT", "/api/product-spaces/{product_space_id}/target-languages"),
}

# 管理面只读：query-actor RBAC 读闸（Q109/Q118，门控开启时 rbac 以已验真
# staff 身份覆盖自报），不挂凭证依赖属既定 V1 契约，不在本用例强制面内。
ADMIN_VIEW_GATED = {
    ("GET", "/api/admin/content/ready-to-publish"),
    ("GET", "/api/admin/content/needs-attention"),
    ("GET", "/api/admin/content/{content_id}"),
    ("GET", "/api/admin/content/{content_id}/script-recheck"),
    ("GET", "/api/admin/content-languages"),
    ("GET", "/api/content/eligible-languages"),
}


def _content_routes() -> dict[tuple[str, str], APIRoute]:
    """content 路由的全部 (method, path)：include_router 包装层递归展开。"""
    routes: dict[tuple[str, str], APIRoute] = {}
    stack = list(app.routes)
    while stack:
        node = stack.pop()
        if isinstance(node, APIRoute):
            if node.endpoint.__module__ == "app.content.router":
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


def _has_credential_marker(route: APIRoute) -> bool:
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        if getattr(call, CLIENT_MARKER, False) or getattr(
            call, INTERNAL_MARKER, False
        ):
            return True
        stack.extend(getattr(dep, "dependencies", []) or [])
    return False


def test_content_route_surface_is_fully_accounted():
    """路由面＝已知集合：新端点必须登记闸型，杜绝「顺手加个裸口」。"""
    routes = _content_routes()
    expected = CLIENT_GATED | STAFF_GATED | ADMIN_VIEW_GATED
    unaccounted = set(routes) - expected
    missing = expected - set(routes)
    assert not unaccounted, f"ungated/undocumented content endpoints: {unaccounted}"
    assert not missing, f"content endpoints removed without updating this test: {missing}"


def test_expected_credential_gates_are_wired():
    routes = _content_routes()
    ungated = [
        op for op in CLIENT_GATED | STAFF_GATED if not _has_credential_marker(routes[op])
    ]
    assert not ungated, f"content endpoints missing credential dependency: {ungated}"
