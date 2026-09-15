"""M12 驾驶舱端点（Q92）：platform_admin 只读，实时聚合。

GET 无请求体先例（agent-keys 列表不过闸）不适用成本/工作量视图——接缝④拍板
platform_admin 只读，故管理面 GET 首次经 query 携带 actor（actor_id 必填，
roles 可重复传），缺 actor_id 由 FastAPI 判 422、角色不符服务前依赖判 403。
真实认证中间件（会话/JWT）随 V2，V1 actor 仍为请求自报口径（同写端点）。
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.dashboards import service
from app.core.db import get_session
from app.core.rbac import PLATFORM_ADMIN, PermissionDenied, require_any_role

router = APIRouter(prefix="/api/admin/dashboards", tags=["dashboards"])


def require_admin_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


@router.get("/token-cost")
async def token_cost_dashboard(
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_admin_view),
) -> dict:
    try:
        return await service.token_cost_summary(
            session, date_from=date_from, date_to=date_to
        )
    except service.DashboardWindowInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/review-workload")
async def review_workload_dashboard(
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_admin_view),
) -> dict:
    try:
        return await service.review_workload(
            session, date_from=date_from, date_to=date_to
        )
    except service.DashboardWindowInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
