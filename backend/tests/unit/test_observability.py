"""阶段 3：OTel trace 导出的单元测试。

只测 env 契约与初始化边界：endpoint 解析、未设 endpoint 时 noop、设了时调用
``set_tracer_provider``。真实 SDK 的导出行为由端到端验证（起服务 → collector →
tempo）覆盖，不在此用全局单例反复重设 provider。
"""
from __future__ import annotations

import os
from unittest.mock import patch

from app.core.observability import init_tracing
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
