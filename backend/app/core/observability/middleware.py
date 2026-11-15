"""OTel HTTP 请求 span 中间件（纯 ASGI，opt-in）。

未初始化 tracer 时（env 未设）``start_as_current_span`` 落在 noop tracer 上，
span 不导出、零行为变化。路径标签沿用路由模板（同 ``MetricsMiddleware``），
避免把 id 带进 span 名造成高基数。
"""
from __future__ import annotations

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.core.observability.trace import get_tracer


class OtelTraceMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        route = scope.get("route")
        path = getattr(route, "path", None) or "unmatched"
        tracer = get_tracer()

        with tracer.start_as_current_span(
            f"{method} {path}",
            kind=SpanKind.SERVER,
            attributes={
                "http.method": method,
                "http.route": path,
            },
        ) as span:
            status_code = 500

            async def send_wrapper(message) -> None:
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                span.set_attribute("http.status_code", status_code)
                if status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR))
