"""Q181：默认指标注册表与 HTTP 指标采集中间件（纯 ASGI，零依赖）。

路径标签使用路由模板（scope["route"].path，如 /api/fcw/{final_id}）而非原始
URL，避免 id 造成高基数；404 无匹配路由记为 "unmatched"。
"""
from __future__ import annotations

from time import perf_counter

from app.core.metrics.registry import Counter, Gauge, Histogram, Registry

REGISTRY = Registry()

UP = Gauge("up", "Process is up (1 means running).")
UP.set(1)

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled, by method, route template and status.",
    ("method", "path", "status"),
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds, by method and route template.",
    ("method", "path"),
)
REGISTRY.register(UP)
REGISTRY.register(HTTP_REQUESTS)
REGISTRY.register(HTTP_LATENCY)


class MetricsMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = perf_counter()
        status_code = 500

        async def send_wrapper(message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            path = getattr(route, "path", None) or "unmatched"
            method = scope.get("method", "")
            HTTP_REQUESTS.inc(
                method=method, path=path, status=str(status_code)
            )
            HTTP_LATENCY.observe(
                perf_counter() - start, method=method, path=path
            )
