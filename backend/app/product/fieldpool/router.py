from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.rbac import PermissionDenied
from app.product.fieldpool import service
from app.product.fieldpool.models import FPDimension
from app.product.fieldpool.schemas import (
    GateDecisionRequest,
    PlanSubmitRequest,
    PromoteRequest,
    RestoreRequest,
    RouteUpsert,
)
from app.product.product_intake.schemas import Actor

router = APIRouter(prefix="/api", tags=["field-pool"])


def _dim_view(d: FPDimension) -> dict:
    return {
        "dimension_id": d.dimension_id,
        "role": d.role,
        "source_route": d.source_route,
        "source_ref": d.source_ref,
        "field_name": d.field_name,
        "definition": d.definition,
        "fid": d.fid,
        "candidate_id": d.candidate_id,
        "confidence": d.confidence,
        "needs_detail": d.needs_detail,
        "dup": d.dup,
        "related_fid": d.related_fid,
        "status": d.status,
        "sort_order": d.sort_order,
    }


async def _pool_payload(session, pool) -> dict:
    dims = await service.list_dimensions(session, pool.pool_id)
    return {
        "pool_id": pool.pool_id,
        "product_space_id": pool.product_space_id,
        "gate": pool.gate,
        "compliant": pool.compliant,
        "violations": pool.violations,
        "target_atom_min": pool.target_atom_min,
        "target_atom_max": pool.target_atom_max,
        "reject_reason": pool.reject_reason,
        "dimensions": [_dim_view(d) for d in dims],
    }


# ---- Q8 来源路由表 ----

@router.get("/admin/fp-source-routes")
async def get_routes(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = await service.list_routes(session)
    return [
        {"route": r.route, "name": r.name, "enabled": r.enabled, "sort_order": r.sort_order}
        for r in rows
    ]


@router.put("/admin/fp-source-routes/{route}")
async def put_route(
    route: str, body: RouteUpsert, session: AsyncSession = Depends(get_session)
) -> dict:
    if body.item.route != route:
        raise HTTPException(status_code=422, detail="route in path and body must match")
    try:
        row = await service.upsert_route(session, body.item, body.actor)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="route already exists") from exc
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"route": row.route}


class _RouteDelete(BaseModel):
    actor: Actor


@router.delete("/admin/fp-source-routes/{route}")
async def delete_route(
    route: str, body: _RouteDelete, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        await service.delete_route(session, route, body.actor)
        await session.commit()
    except service.RouteInUse as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="route is referenced by dimensions") from exc
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"deleted": route}


# ---- 字段池方案 ----

@router.post("/product-spaces/{product_space_id}/field-pools")
async def submit_plan(
    product_space_id: str,
    body: PlanSubmitRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        pool = await service.submit_plan(session, product_space_id, body, body.actor)
        await session.commit()
    except service.ProductSpaceNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="product space not found") from exc
    except (service.InvalidPlan, service.GateNotAllowed) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.refresh(pool)
    return await _pool_payload(session, pool)


@router.get("/product-spaces/{product_space_id}/field-pools/current")
async def get_current_pool(
    product_space_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        pool = await service.get_pool(session, product_space_id)
    except service.ProductSpaceNotFound as exc:
        raise HTTPException(status_code=404, detail="product space not found") from exc
    if pool is None:
        raise HTTPException(status_code=404, detail="field pool not found")
    return await _pool_payload(session, pool)


@router.post("/field-pools/{pool_id}/gate")
async def decide_gate(
    pool_id: str, body: GateDecisionRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        pool = await service.decide_gate(session, pool_id, body, body.actor)
        await session.commit()
    except service.PoolNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="field pool not found") from exc
    except service.InvalidPlan as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _pool_payload(session, pool)


@router.post("/field-pools/{pool_id}/dimensions/{dimension_id}/restore")
async def restore_dimension(
    pool_id: str,
    dimension_id: str,
    body: RestoreRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        pool = await service.restore_dimension(session, pool_id, dimension_id, body.actor)
        await session.commit()
    except service.PoolNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="field pool not found") from exc
    except service.DimensionNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="dimension not found") from exc
    except (service.InvalidPlan, service.GateNotAllowed) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _pool_payload(session, pool)


# ---- Q13 候选转正 ----

@router.get("/admin/g2-candidates")
async def list_candidates(
    status: str | None = None, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    rows = await service.list_candidates(session, status)
    return [
        {
            "candidate_id": c.candidate_id,
            "tenant_id": c.tenant_id,
            "field_name": c.field_name,
            "definition": c.definition,
            "source_layer": c.source_layer,
            "source_route": c.source_route,
            "confidence": c.confidence,
            "dup": c.dup,
            "related_fid": c.related_fid,
            "status": c.status,
        }
        for c in rows
    ]


@router.post("/admin/g2-candidates/{candidate_id}/promote")
async def promote_candidate(
    candidate_id: str, body: PromoteRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        field = await service.promote_candidate(session, candidate_id, body, body.actor)
        await session.commit()
    except service.CandidateNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="candidate not found") from exc
    except service.InvalidPlan as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.FidConflict as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"fid": field.fid, "cat": field.cat, "field_name": field.field_name}
