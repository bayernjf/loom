"""restock_auto worker 管理端点：手工触发一轮（Q87，同 SLA /run 口径）。"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session, settings
from app.core.locking import (
    RESTOCK_LOCK,
    LockBackendError,
    LockUnavailable,
    leader_lock,
)
from app.core.rbac import PLATFORM_ADMIN, PermissionDenied, require_any_role
from app.core.restock.worker import run_restock

router = APIRouter(prefix="/api/admin/restock", tags=["restock"])


class _RestockBody(BaseModel):
    actor: Actor


@router.post("/run")
async def run_restock_once(
    body: _RestockBody, session: AsyncSession = Depends(get_session)
) -> dict:
    """手工触发一轮 restock 消费（与定时 worker 同一 runner，每条信号独立提交）。

    手工触发归 platform_admin（同 Q75 SLA /run）；定时 worker 为系统内部调度不经此闸。
    多副本下与定时 worker 抢同一把 leader 锁（Q89），抢不到 409、锁后端故障 503。
    Q90：platform_admin 显式"立即试一次"，绕过退避窗口（瞬态仍累加 attempts 并重排窗口）。
    """
    try:
        require_any_role(body.actor, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    @asynccontextmanager
    async def factory() -> AsyncGenerator[AsyncSession, None]:
        yield session

    try:
        async with leader_lock(RESTOCK_LOCK):
            return await run_restock(
                factory,
                limit=settings.restock_batch_size,
                honor_backoff=False,
            )
    except LockUnavailable as exc:
        raise HTTPException(
            status_code=409, detail="restock sweep already running"
        ) from exc
    except LockBackendError as exc:
        raise HTTPException(status_code=503, detail="lock backend unavailable") from exc
