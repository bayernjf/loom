"""SLA 引擎管理端点：手工触发全量 sweep + 待办 SLA 看板视图（Q49/Q70）。"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.locking import (
    SWEEP_LOCK,
    LockBackendError,
    LockLost,
    LockUnavailable,
    leader_lease,
)
from app.core.rbac import PLATFORM_ADMIN, PermissionDenied, require_any_role
from app.core.sla.fencing import TICK_LOST, claim_tick, fence_current
from app.core.sla.policies import sla_state
from app.core.sla.runner import run_jobs
from app.product.modeling.models import OpsTodo

router = APIRouter(prefix="/api/admin/sla", tags=["sla"])

# Q108：看板状态过滤白名单（OpsTodo.status 三态 + all）；非法值 422。
TODO_STATUS_FILTERS = {"open", "escalated", "resolved", "all"}


def require_sla_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


class _SweepBody(BaseModel):
    actor: Actor


@router.post("/run")
async def run_sweep(
    body: _SweepBody, session: AsyncSession = Depends(get_session)
) -> dict:
    """手工触发全部 SLA 作业（与定时调度同一 runner，每作业独立提交/回滚）。

    手工触发归 platform_admin（Q75）；定时调度为系统内部调用，不经此闸。
    多副本下与定时调度抢同一把 leader 锁（Q89），抢不到 409、锁后端故障 503。
    """
    try:
        require_any_role(body.actor, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    @asynccontextmanager
    async def factory() -> AsyncGenerator[AsyncSession, None]:
        yield session

    try:
        async with leader_lease(SWEEP_LOCK) as lease:
            # Q151：与定时调度同一套 PG 行级 fence：先短事务认领本 tick，再以
            # 每作业提交前条件更新门，挡住手工触发与定时 tick 重叠时的迟到写入。
            if lease.fence is not None:
                outcome = await claim_tick(
                    session, SWEEP_LOCK, lease.fence, lease.owner_token
                )
                if outcome == TICK_LOST:
                    raise HTTPException(
                        status_code=409,
                        detail="sweep aborted: tick claim held by a newer leader",
                    )
                await session.commit()

            async def commit_guard(guard_session: AsyncSession) -> bool:
                return await fence_current(guard_session, SWEEP_LOCK, lease.fence)

            # Q139：作业间协作中止，锁中途易主则本轮剩余作业不再执行。
            return await run_jobs(
                factory,
                checkpoint=lease.raise_if_lost,
                commit_guard=commit_guard,
            )
    except LockUnavailable as exc:
        raise HTTPException(status_code=409, detail="sweep already running") from exc
    except LockLost as exc:
        raise HTTPException(
            status_code=409, detail="sweep aborted: leader lock lost mid-run"
        ) from exc
    except LockBackendError as exc:
        raise HTTPException(status_code=503, detail="lock backend unavailable") from exc


@router.get("/todos")
async def todo_board(
    status: str = "open",
    _: Actor = Depends(require_sla_view),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """待办看板：附带派生 sla_state（green/yellow/red/resolved；黄色口径见 policies）。"""
    if status not in TODO_STATUS_FILTERS:
        raise HTTPException(status_code=422, detail=f"unknown todo status: {status}")
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
