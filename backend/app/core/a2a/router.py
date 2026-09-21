"""A2A 封臣路由（Q150）：卡片发现（公开）+ 任务端点（Q88 Agent Key 保护 + 审计）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.a2a import rpc
from app.core.a2a.card import build_agent_card
from app.core.api_keys.models import AgentApiKey
from app.core.api_keys.service import require_agent_key
from app.core.audit import append_audit
from app.core.db import get_session

router = APIRouter(tags=["a2a-vassal"])

PLATFORM_TENANT = "_platform"


async def _require_zeus_key(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> AgentApiKey:
    """Q150：任务端点复用 Q88 Agent Key 验签（与 effect-callback 同一凭证体系）。"""
    return await require_agent_key(session, authorization)


async def _audit_task(session: AsyncSession, key: AgentApiKey, task: dict[str, Any]) -> None:
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=key.key_id,
        actor_roles=None,
        action="a2a.task",
        entity_type="a2a_task",
        entity_id=task["id"],
        detail={
            "agent_key": key.name,
            "skill": task["artifacts"][0]["parts"][0]["data"]["skill"] if task.get("artifacts") else None,
            "state": task["status"]["state"],
            "run_id": (task.get("metadata") or {}).get("x-zeus-runId"),
        },
    )
    await session.commit()


def _card_response() -> JSONResponse:
    return JSONResponse(build_agent_card(), headers={"Cache-Control": "public, max-age=300"})


@router.get("/api/a2a/agent-card")
async def agent_card() -> JSONResponse:
    return _card_response()


@router.get("/.well-known/agent-card.json")
async def agent_card_well_known() -> JSONResponse:
    return _card_response()


@router.get("/.well-known/agent.json")
async def agent_card_well_known_legacy() -> JSONResponse:
    return _card_response()


@router.post("/api/a2a/tasks")
async def tasks(
    payload: dict,
    key: AgentApiKey = Depends(_require_zeus_key),
    session: AsyncSession = Depends(get_session),
) -> Any:
    method = payload.get("method")
    if method == "tasks/sendSubscribe":
        return StreamingResponse(
            _subscribe_stream(payload, key, session),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
    response = rpc.handle_jsonrpc(payload)
    if isinstance(response.get("result"), dict) and response["result"].get("kind") == "task":
        await _audit_task(session, key, response["result"])
    return JSONResponse(response)


async def _subscribe_stream(payload: dict, key: AgentApiKey, session: AsyncSession) -> AsyncIterator[str]:
    events: list[dict] = []

    def collect(event: dict) -> None:
        events.append(event)

    response = rpc.handle_jsonrpc(payload, on_event=collect)
    for event in events:
        yield f"data: {json.dumps({'jsonrpc': '2.0', 'id': payload.get('id'), 'result': event})}\n\n"
    yield f"data: {json.dumps(response)}\n\n"
    if isinstance(response.get("result"), dict) and response["result"].get("kind") == "task":
        await _audit_task(session, key, response["result"])
