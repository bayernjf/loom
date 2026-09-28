"""MCP HTTP 路由（Q232）：`POST /mcp` ＋ Q88 Agent Key 鉴权 ＋ 审计 ＋ 门控默认关。

鉴权与 A2A 任务端点同一套凭证体系（复用 Q88 `require_agent_key`，缺失/错误/吊销统一 401）；
门控 `LOOM_MCP_ENABLED` 默认关 ⇒ 关时对本路径回 **404** 而非 403——不向外暴露"这里有个东西"。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_keys.models import AgentApiKey
from app.core.api_keys.service import require_agent_key
from app.core.audit import append_audit
from app.core.config import get_settings
from app.core.db import get_session
from app.core.mcp import server as mcp

router = APIRouter(tags=["mcp"])

PLATFORM_TENANT = "_platform"


async def _require_machine_key(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> AgentApiKey:
    """Q88 依赖需要位置参 session，故与 Q150 同法包一层（不能直接 Depends(require_agent_key)）。"""
    return await require_agent_key(session, authorization)


@router.post("/mcp")
async def mcp_endpoint(
    payload: dict,
    session: AsyncSession = Depends(get_session),
    key: AgentApiKey = Depends(_require_machine_key),
) -> Any:
    if not get_settings().mcp_enabled:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32601, "message": "MCP endpoint disabled"}},
            status_code=404,
        )
    response = mcp.handle(payload)
    body = {"jsonrpc": "2.0", "id": payload.get("id"), **response}
    await _audit(session, key, payload, response)
    return JSONResponse(body)


async def _audit(session: AsyncSession, key: AgentApiKey, payload: dict, response: dict) -> None:
    """每次调用都留痕（同 Q150 `a2a.task` 口径：错误与 input_required 也留）。"""
    params = payload.get("params") or {}
    result = response.get("result") or {}
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=key.key_id,
        actor_roles=None,
        action="mcp.request",
        entity_type="mcp_request",
        entity_id=str(payload.get("id") or ""),
        detail={
            "agent_key": key.name,
            "method": payload.get("method"),
            "tool": params.get("name") if payload.get("method") == "tools/call" else None,
            "result_type": result.get("resultType"),
            "error_code": (response.get("error") or {}).get("code"),
        },
    )
    await session.commit()
