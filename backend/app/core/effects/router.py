"""段13 效果回流端点（Q126）：入站 POST /api/effect-callback + 运营只读队列。"""

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.api_keys.models import AgentApiKey
from app.core.api_keys.service import require_agent_key
from app.core.db import get_session
from app.core.effects import service
from app.core.effects.schemas import (
    EffectBatchIn,
    EffectBatchReceipt,
    EffectRecordView,
)
from app.core.rbac import (
    OPERATIONS,
    PLATFORM_ADMIN,
    PermissionDenied,
    require_any_role,
)

router = APIRouter(tags=["effects"])


async def require_effect_key(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> AgentApiKey:
    """入站 Bearer Agent Key 验签（Q88 已备依赖，段13 首个受保护消费端点）。"""

    return await require_agent_key(session, authorization)


def _query_actor(*roles: str):
    """管理面读口 query actor 闸（同 Q109/Q118/Q125：缺 actor_id 422、越权 403）。"""

    def dependency(
        actor_id: str = Query(...),
        roles_param: list[str] = Query(default_factory=list, alias="roles"),
    ) -> Actor:
        actor = Actor(id=actor_id, roles=roles_param)
        try:
            require_any_role(actor, *roles)
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return actor

    return dependency


require_ops_admin_view = _query_actor(OPERATIONS, PLATFORM_ADMIN)


@router.post("/api/effect-callback", response_model=EffectBatchReceipt)
async def receive_effects(
    body: EffectBatchIn,
    key: AgentApiKey = Depends(require_effect_key),
    session: AsyncSession = Depends(get_session),
) -> EffectBatchReceipt:
    """全链唯一反向边数据入口（Q60）：外部 Agent 推送效果时序，整批 all-or-nothing。"""

    try:
        receipt = await service.ingest_effects(session, batch=body, key=key)
    except service.EffectValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "index": exc.index,
                "field": exc.field,
                "message": str(exc),
            },
        ) from exc
    await session.commit()
    return EffectBatchReceipt(**receipt)


@router.get(
    "/api/admin/effects/orphans",
    response_model=list[EffectRecordView],
)
async def list_orphan_effects(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=500),
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_ops_admin_view),
) -> list[dict]:
    """孤儿数据队列（Q60）：对不上本系统 content_id 的推送，供人工认领（认领随下一片）。"""

    rows = await service.list_orphans(session, limit=limit, offset=offset)
    return [service.effect_view(row) for row in rows]


@router.get(
    "/api/admin/effects",
    response_model=list[EffectRecordView],
)
async def list_content_effects(
    content_id: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=500),
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_ops_admin_view),
) -> list[dict]:
    """某成品的效果时间序列（同 content_id 按 captured_at 升序追加）。"""

    rows = await service.list_series(session, content_id, limit=limit, offset=offset)
    return [service.effect_view(row) for row in rows]
