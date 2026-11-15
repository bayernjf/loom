"""阶段 3：OTel trace 导出的单元测试。

覆盖两层：env 契约与初始化边界（endpoint 解析、未设 endpoint 时 noop、设了时调用
``set_tracer_provider``），以及中间件在 router 回填 ``scope["route"]`` 后把 span 名
从原始 path 收窄为路由模板（避免把 id 带进 span 名）。真实 SDK 的导出行为由
端到端验证（起服务 → collector → tempo）覆盖。
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch

from app.core.observability import init_tracing
from app.core.observability.middleware import OtelTraceMiddleware
from app.core.observability.trace import _endpoint


def test_endpoint_none_when_unset():
    with patch.dict(os.environ, {}, clear=True):
        assert _endpoint() is None


def test_endpoint_parses_value():
    with patch.dict(
        os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/v1/traces"}
    ):
        assert _endpoint() == "http://collector:4318/v1/traces"


def test_init_tracing_is_noop_when_endpoint_unset():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("app.core.observability.trace.trace.set_tracer_provider") as mock_set,
    ):
        init_tracing()
        mock_set.assert_not_called()


def test_init_tracing_sets_provider_when_endpoint_set():
    with (
        patch.dict(
            os.environ,
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/v1/traces"},
        ),
        patch("app.core.observability.trace.OTLPSpanExporter"),
        patch("app.core.observability.trace.BatchSpanProcessor"),
        patch("app.core.observability.trace.trace.set_tracer_provider") as mock_set,
    ):
        init_tracing()
        mock_set.assert_called_once()


def test_middleware_renames_span_from_route_template():
    span = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=span)
    cm.__exit__ = MagicMock(return_value=False)
    tracer = MagicMock()
    tracer.start_as_current_span.return_value = cm

    route = type("_Route", (), {"path": "/users/{user_id}"})()

    async def inner_app(scope, receive, send):
        scope["route"] = route  # 模拟 router 在中间件之后回填
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = OtelTraceMiddleware(inner_app)

    async def run():
        scope = {"type": "http", "method": "GET", "path": "/users/42", "headers": []}

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            return None

        await mw(scope, receive, send)

    with patch("app.core.observability.middleware.get_tracer", return_value=tracer):
        asyncio.run(run())

    # 起 span 时用原始 path（router 尚未回填 route）
    assert tracer.start_as_current_span.call_args.args[0] == "GET /users/42"
    # 请求结束后收窄成路由模板
    span.update_name.assert_called_once_with("GET /users/{user_id}")
    span.set_attribute.assert_any_call("http.route", "/users/{user_id}")
    span.set_attribute.assert_any_call("http.status_code", 200)
