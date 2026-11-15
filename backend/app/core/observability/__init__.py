"""OTel trace 导出（阶段 3，opt-in，官方 Python OTel SDK + 自写 ASGI 中间件）。

统一 env 契约（与 zeus / agent-world 一致）：``OTEL_EXPORTER_OTLP_ENDPOINT``
空=不初始化、``OTEL_SERVICE_NAME`` 默认 loom-backend、``deployment.environment``
默认 local。
"""
from app.core.observability.middleware import OtelTraceMiddleware
from app.core.observability.trace import get_tracer, init_tracing

__all__ = ["OtelTraceMiddleware", "get_tracer", "init_tracing"]
