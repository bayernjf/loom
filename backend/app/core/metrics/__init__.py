"""Q181：进程内指标（零依赖 Prometheus 文本）+ HTTP 中间件 + /metrics 端点。"""
from app.core.metrics.middleware import (
    HTTP_LATENCY,
    HTTP_REQUESTS,
    REGISTRY,
    UP,
    MetricsMiddleware,
)
from app.core.metrics.registry import (
    DEFAULT_BUCKETS,
    Counter,
    Gauge,
    Histogram,
    Metric,
    Registry,
)
from app.core.metrics.router import router

__all__ = [
    "DEFAULT_BUCKETS",
    "HTTP_LATENCY",
    "HTTP_REQUESTS",
    "REGISTRY",
    "UP",
    "Counter",
    "Gauge",
    "Histogram",
    "Metric",
    "MetricsMiddleware",
    "Registry",
    "router",
]
