"""OTel trace 导出初始化（阶段 3，opt-in，官方 Python OTel SDK）。

统一 env 契约（与 zeus / agent-world 一致）：
- ``OTEL_EXPORTER_OTLP_ENDPOINT`` 空/未设 = 不初始化（noop，零开销、零副作用）；
- ``OTEL_SERVICE_NAME`` 默认 ``loom-backend``；
- ``deployment.environment`` 默认 ``local``。

只引 opentelemetry-api / sdk / exporter-otlp-proto-http 三个包；ASGI 中间件
自写，不引 opentelemetry-instrumentation-*，避免带进整套 instrumentation 依赖。
初始化失败一律降级为 noop，绝不影响主进程启动。
"""
from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger("loom.observability")

_TRACER_NAME = "loom-backend"
_SERVICE_NAME_DEFAULT = "loom-backend"


def _endpoint() -> str | None:
    value = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    return value or None


def init_tracing() -> None:
    """设置全局 ``TracerProvider``（opt-in）。

    未设 ``OTEL_EXPORTER_OTLP_ENDPOINT`` 时直接返回，后续 ``trace.get_tracer``
    落在 SDK 默认的 noop tracer 上，不导出、无行为变化。
    """
    endpoint = _endpoint()
    if endpoint is None:
        return
    try:
        service_name = (
            os.environ.get("OTEL_SERVICE_NAME", "").strip() or _SERVICE_NAME_DEFAULT
        )
        environment = os.environ.get("DEPLOY_ENV", "").strip() or "local"
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": service_name,
                    "deployment.environment": environment,
                }
            )
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        logger.info(
            "otlp trace export enabled: endpoint=%s service=%s env=%s",
            endpoint,
            service_name,
            environment,
        )
    except Exception as exc:  # noqa: BLE001 - 环境异常兜底，不阻断启动
        logger.warning("otlp trace export disabled: init failed: %s", exc)


def get_tracer() -> trace.Tracer:
    """返回具名 tracer；未初始化时为 noop tracer。"""
    return trace.get_tracer(_TRACER_NAME)
