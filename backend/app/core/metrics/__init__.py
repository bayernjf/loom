"""Q181：进程内指标（零依赖 Prometheus 文本）+ HTTP 中间件 + /metrics 端点。

Q188：业务级序列登记在 ``business``，导入本包即完成注册（``app/main.py`` 已
import 本包），故 ``/metrics`` 无需任何端点改动就带出业务族。
"""
# business 把七族注册进 middleware 里那个同一个 REGISTRY。
from app.core.metrics.business import (
    JOBS_FAILED,
    LLM_BUDGET_BLOCKED,
    LLM_UPSTREAM_DURATION,
    LOCK_LOST,
    STREAM_DEAD_LETTERS,
    STREAM_LENGTH,
    STREAM_PENDING,
    observe_llm_call,
    record_budget_blocked,
    record_dead_letter,
    record_job_failed,
    record_lock_lost,
    set_stream_depth,
)
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
    "JOBS_FAILED",
    "LLM_BUDGET_BLOCKED",
    "LLM_UPSTREAM_DURATION",
    "LOCK_LOST",
    "REGISTRY",
    "STREAM_DEAD_LETTERS",
    "STREAM_LENGTH",
    "STREAM_PENDING",
    "UP",
    "Counter",
    "Gauge",
    "Histogram",
    "Metric",
    "MetricsMiddleware",
    "Registry",
    "observe_llm_call",
    "record_budget_blocked",
    "record_dead_letter",
    "record_job_failed",
    "record_lock_lost",
    "router",
    "set_stream_depth",
]
