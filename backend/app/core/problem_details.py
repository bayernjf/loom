"""统一错误响应契约（RFC 9457 ProblemDetails，Tier0 评审 2026-10-30 H2 收口）。

未识别异常与上游/管道异常的原文（可能携带表名、驱动细节、上游响应体片段）
只进服务端日志；客户端收到固定泛化 detail：

- 全局兜底：FastAPI ``Exception`` handler 返回最小 ProblemDetails 形状
  ``{type, title, status, detail, instance}``，固定 ``detail="internal error"``。
- router 层既有 ``except`` → ``HTTPException`` 映射保留原状态码，仅把回显
  ``str(exc)`` 的位置换成 ``logged_http_error``（原文进日志）。

带错误码的业务错误（service.*、rbac.*、gateway 配置类等类型化异常）继续沿用
各 router 既有语义化 detail 与 ``{"detail": ...}`` 形状，零变化。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request

logger = logging.getLogger("loom.errors")

_PROBLEM_TITLES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
}


def problem_details_body(request: Request, status_code: int, detail: str) -> dict[str, Any]:
    """RFC 9457 最小 ProblemDetails 体（application/json 承载，detail 固定泛化）。"""
    return {
        "type": "about:blank",
        "title": _PROBLEM_TITLES.get(status_code, "Error"),
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
    }


def problem_response(request: Request, status_code: int, detail: str) -> JSONResponse:
    """把 ProblemDetails 体包成 JSONResponse。"""
    return JSONResponse(
        status_code=status_code, content=problem_details_body(request, status_code, detail)
    )


def logged_http_error(status_code: int, detail: str, exc: Exception) -> HTTPException:
    """异常原文只进服务端日志，客户端收固定泛化 detail。

    返回的仍是 ``HTTPException``，响应形状（``{"detail": ...}``）与状态码
    都不变——只有"不再回显异常原文"这一点变化。
    """
    logger.warning("endpoint failure: %s: %s", type(exc).__name__, exc)
    return HTTPException(status_code=status_code, detail=detail)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局兜底：未识别异常返回固定 ProblemDetails，原文与栈只进日志。"""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return problem_response(request, 500, "internal error")
