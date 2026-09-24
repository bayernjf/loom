"""Q181：GET /metrics——输出 Prometheus 文本 exposition（默认不鉴权，同 /healthz）。"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.metrics.middleware import REGISTRY

router = APIRouter()


@router.get("/metrics")
async def metrics() -> Response:
    return Response(
        REGISTRY.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
