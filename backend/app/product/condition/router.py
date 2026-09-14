from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.product.condition import service
from app.product.condition.models import (
    ConditionPackage,
    ContentGoal,
    PwcComboItem,
)
from app.product.condition.schemas import (
    ActorRequest,
    ConsumeRequest,
    FunnelRequest,
    GateRequest,
    GoalArchiveRequest,
    GoalUpsertRequest,
    HotMarkRequest,
    PoolConfigRequest,
)

router = APIRouter(prefix="/api", tags=["pwc"])


def _goal_view(g: ContentGoal) -> dict:
    return {
        "code": g.code,
        "color": g.color,
        "ratio_min": g.ratio_min,
        "ratio_max": g.ratio_max,
        "status": g.status,
    }


def _pwc_view(p: ConditionPackage, items: list[PwcComboItem] | None = None) -> dict:
    return {
        "pwc_id": p.pwc_id,
        "product_space_id": p.product_space_id,
        "source": p.source,
        "goals": p.goals,
        "weight": p.weight,
        "compliance": p.compliance_result,
        "score": p.score,
        "score_detail": p.score_detail,
        "score_incomplete": p.score_incomplete,
        "dup_of": p.dup_of,
        "is_backup": p.is_backup,
        "gate_status": p.gate_status,
        "status": p.status,
        "reject_reason": p.reject_reason,
        "usage_count": p.usage_count,
        "high_reuse": p.high_reuse,
        "is_hot": p.is_hot,
        "combo_atom_ids": [i.atom_id for i in (items or [])],
    }


# ---- Q25 contentGoals 字典 ----

@router.get("/admin/content-goals")
async def list_goals(
    include_archived: bool = False, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    rows = await service.list_goals(session, include_archived=include_archived)
    return [_goal_view(g) for g in rows]


@router.put("/admin/content-goals")
async def upsert_goal(
    body: GoalUpsertRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        goal = await service.upsert_goal(session, body, body.actor)
        await session.commit()
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.GoalInvalid as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _goal_view(goal)


@router.post("/admin/content-goals/{code}/archive")
async def archive_goal(
    code: str, body: GoalArchiveRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        await service.archive_goal(session, code, body.actor)
        await session.commit()
    except service.GoalNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="content goal not found") from exc
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"code": code, "status": "archived"}


# ---- Q27 库容配置 ----

@router.get("/product-spaces/{product_space_id}/pwc-pool-config")
async def get_pool_config(
    product_space_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    return await service.get_pool_config(session, product_space_id)


@router.put("/product-spaces/{product_space_id}/pwc-pool-config")
async def set_pool_config(
    product_space_id: str,
    body: PoolConfigRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        await service.set_pool_config(session, product_space_id, body, body.actor)
        await session.commit()
    except service.ProductSpaceNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="product space not found") from exc
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return await service.get_pool_config(session, product_space_id)


# ---- Q21 漏斗 ----

@router.post("/product-spaces/{product_space_id}/pwc/funnel")
async def run_funnel(
    product_space_id: str,
    body: FunnelRequest,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    try:
        created = await service.run_funnel(session, product_space_id, body, body.actor)
        await session.commit()
    except service.ProductSpaceNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="product space not found") from exc
    except service.PoolNotApproved as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.InvalidFunnel as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    items = await service.list_combo_items(session, [p.pwc_id for p in created])
    return [_pwc_view(p, items.get(p.pwc_id)) for p in created]


@router.get("/product-spaces/{product_space_id}/pwcs")
async def list_pwcs(
    product_space_id: str,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = await service.list_pwcs(session, product_space_id, status)
    items = await service.list_combo_items(session, [p.pwc_id for p in rows])
    return [_pwc_view(p, items.get(p.pwc_id)) for p in rows]


# ---- Gate / 爆款 / 归档 ----

@router.post("/pwcs/{pwc_id}/gate")
async def gate(
    pwc_id: str, body: GateRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        pwc = await service.gate(session, pwc_id, body.decision, body.reason, body.actor)
        await session.commit()
    except service.PwcNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="PWC not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    except service.CapacityFull as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    items = await service.list_combo_items(session, [pwc.pwc_id])
    return _pwc_view(pwc, items.get(pwc_id))


@router.post("/pwcs/{pwc_id}/hot")
async def mark_hot(
    pwc_id: str, body: HotMarkRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        pwc = await service.mark_hot(session, pwc_id, body.is_hot, body.actor)
        await session.commit()
    except service.PwcNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="PWC not found") from exc
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"pwc_id": pwc_id, "is_hot": pwc.is_hot}


@router.post("/pwcs/{pwc_id}/archive")
async def archive_pwc(
    pwc_id: str, body: ActorRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        pwc = await service.archive_pwc(session, pwc_id, body.actor)
        await session.commit()
    except service.PwcNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="PWC not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    return {"pwc_id": pwc_id, "status": pwc.status}


# ---- Q71 消费 ----

@router.post("/product-spaces/{product_space_id}/pwc/consume")
async def consume(
    product_space_id: str,
    body: ConsumeRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        result = await service.consume(session, product_space_id, body, body.actor)
        await session.commit()
    except service.ProductSpaceNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="product space not found") from exc
    except service.PoolEmpty as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    pwc = result["pwc"]
    items = await service.list_combo_items(session, [pwc.pwc_id])
    return {
        "pwc": _pwc_view(pwc, items.get(pwc.pwc_id)),
        "usage_record_id": result["record"].record_id,
        "platform_state": {
            "platform": result["platform_state"].platform,
            "state": result["platform_state"].state,
            "cooldown_until": result["platform_state"].cooldown_until,
        },
        "pool_ready_count": result["pool_ready_count"],
        "pool_health": result["pool_health"],
        "restock_hint": result["restock_hint"],
        "restock_run_id": result["restock_run_id"],
    }
