"""段13 效果回流端点（Q126–Q129）：入站推送、孤儿认领/批量/解绑、客户回填 + 运营只读队列。"""

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.api_keys.models import AgentApiKey
from app.core.api_keys.service import require_agent_key
from app.core.db import get_session, settings
from app.core.effects import service
from app.core.effects.csv_io import CsvValidationError
from app.core.effects.schemas import (
    CustomerBackfillUploadIn,
    CustomerBackfillUploadReceipt,
    CustomerEffectBatchIn,
    EffectBatchIn,
    EffectBatchReceipt,
    EffectClaimBatchRequest,
    EffectClaimBatchView,
    EffectClaimRequest,
    EffectClaimView,
    EffectRecordView,
    EffectUnclaimRequest,
    EffectUnclaimView,
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


# ---------- Q128：客户回填通道（无 Agent Key，body actor + tenant 行级隔离） ----------


@router.post("/api/effects/backfill", response_model=EffectBatchReceipt)
async def customer_backfill_effects(
    body: CustomerEffectBatchIn,
    session: AsyncSession = Depends(get_session),
) -> EffectBatchReceipt:
    """Q128 客户专用效果回填（source 固定 customer-backfill）。

    只接受本租户非 discarded 成品，对不上即整批 422（客户通道绝不产生孤儿）；
    幂等/时序/metrics 纪律与 Agent 通道一致。
    """

    try:
        receipt = await service.ingest_customer_backfill(session, batch=body)
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


@router.post(
    "/api/effects/backfill/upload",
    response_model=CustomerBackfillUploadReceipt,
)
async def customer_backfill_upload(
    body: CustomerBackfillUploadIn,
    session: AsyncSession = Depends(get_session),
) -> CustomerBackfillUploadReceipt:
    """Q156 客户批量 CSV 服务端上传（销 Q136 服务端上传/逐行回执挂账）。

    整份 CSV 挂一个成品；服务端解析固定 9 列表头、逐行校验，任一结构/行错误
    整批 422 回全部坏行明细（index 数据行 0 基 / line 含表头物理行号），不入库；
    全合法才走 Q128 整批 all-or-nothing（只命中本租户非 discarded 成品、绝不孤儿）。
    时间戳必须带时区（服务端无客户时区，naive 逐行报错）；Excel/异步导入随 V2。
    """

    try:
        receipt = await service.ingest_customer_backfill_upload(
            session,
            body=body,
            max_rows=settings.backfill_upload_max_rows,
        )
    except CsvValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={"message": "CSV validation failed", "errors": exc.errors},
        ) from exc
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
    return CustomerBackfillUploadReceipt(**receipt)


# ---------- Q127/Q60a：运营人工认领孤儿（管理面写口，actor 在体，operations 闸） ----------


@router.post("/api/admin/effects/claims", response_model=EffectClaimView)
async def claim_orphan_effect(
    body: EffectClaimRequest,
    session: AsyncSession = Depends(get_session),
) -> EffectClaimView:
    """把孤儿队列中的一条记录人工绑定到本系统成品（持久映射，后续推送不再回落孤儿）。"""

    try:
        result = await service.claim_orphan(
            session,
            record_id=body.record_id,
            content_id=body.content_id,
            actor=body.actor,
        )
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (service.ClaimRecordNotFound, service.ClaimTargetNotFound) as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (service.ClaimRecordNotOrphan, service.ClaimTargetDiscarded) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return EffectClaimView(**result)


@router.post("/api/admin/effects/claims/batch", response_model=EffectClaimBatchView)
async def claim_orphan_effects_batch(
    body: EffectClaimBatchRequest,
    session: AsyncSession = Depends(get_session),
) -> EffectClaimBatchView:
    """Q129：批量人工认领（整批 all-or-nothing；批内 record_id 重复 422）。"""

    try:
        result = await service.claim_orphan_batch(
            session, items=body.items, actor=body.actor
        )
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
    except (service.ClaimRecordNotFound, service.ClaimTargetNotFound) as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (service.ClaimRecordNotOrphan, service.ClaimTargetDiscarded) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return EffectClaimBatchView(**result)


@router.post("/api/admin/effects/claims/unclaim", response_model=EffectUnclaimView)
async def unclaim_orphan_effect(
    body: EffectUnclaimRequest,
    session: AsyncSession = Depends(get_session),
) -> EffectUnclaimView:
    """Q129：取消认领/解绑——删映射，人工认领回填的行回滚 orphan（自动 matched 行不动）。"""

    try:
        result = await service.unclaim_orphan(
            session,
            external_content_id=body.external_content_id,
            actor=body.actor,
        )
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ClaimMappingNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return EffectUnclaimView(**result)


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
