"""SLA 引擎管理端点：手工触发全量 sweep + 待办 SLA 看板视图（Q49/Q70）。"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.rbac import PLATFORM_ADMIN, PermissionDenied, require_any_role
from app.core.sla.policies import sla_state
from app.core.sla.runner import run_jobs
from app.product.modeling.models import OpsTodo

router = APIRouter(prefix="/api/admin/sla", tags=["sla"])


class _SweepBody(BaseModel):
    actor: Actor


@router.post("/run")
async def run_sweep(
    body: _SweepBody, session: AsyncSession = Depends(get_session)
) -> dict:
    """手工触发全部 SLA 作业（与定时调度同一 runner，每作业独立提交/回滚）。

    手工触发归 platform_admin（Q75）；定时调度为系统内部调用，不经此闸。
    """
    try:
        require_any_role(body.actor, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    @asynccontextmanager
    async def factory() -> AsyncGenerator[AsyncSession, None]:
        yield session

    return await run_jobs(factory)


@router.get("/todos")
async def todo_board(
    status: str = "open",
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """待办看板：附带派生 sla_state（green/yellow/red/resolved；黄色口径见 policies）。"""
    now = datetime.now(UTC)
    stmt = select(OpsTodo).order_by(OpsTodo.due_at.asc())
    if status != "all":
        stmt = stmt.where(OpsTodo.status == status)
    rows = (await session.scalars(stmt)).all()
    return [
        {
            "todo_id": t.todo_id,
            "tenant_id": t.tenant_id,
            "todo_type": t.todo_type,
            "entity_type": t.entity_type,
            "entity_id": t.entity_id,
            "status": t.status,
            "assignee_role": t.assignee_role,
            "due_at": t.due_at.isoformat(),
            "escalated_at": t.escalated_at.isoformat() if t.escalated_at else None,
            "sla_state": sla_state(t, now),
        }
        for t in rows
    ]
