"""段6 PWS 冻结 HTTP（开发补规格；PT-PWS-FREEZE 为 12 #15 占位）。

错误口径：不存在 404 / 角色不符 403 / 状态或就绪门不允许 409 /
重冻原因校验失败 422；所有写操作 writeAudit。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.product.whitelist_center import service
from app.product.whitelist_center.models import PwsSnapshot
from app.product.whitelist_center.schemas import (
    FreezeRequest,
    ReadinessEvaluateRequest,
    RevokeRequest,
)

router = APIRouter(prefix="/api", tags=["pws"])


def _snapshot_view(snapshot: PwsSnapshot, items: list | None = None) -> dict:
    view = {
        "pws_id": snapshot.pws_id,
        "tenant_id": snapshot.tenant_id,
        "product_space_id": snapshot.product_space_id,
        "version": snapshot.version,
        "status": snapshot.status,
        "is_active": snapshot.is_active,
        "pool_id": snapshot.pool_id,
        "fingerprint": snapshot.fingerprint,
        "readiness": snapshot.readiness,
        "refreeze_tier": snapshot.refreeze_tier,
        "reason_code": snapshot.reason_code,
        "superseded_by": snapshot.superseded_by,
        "created_by": snapshot.created_by,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "revoked_by": snapshot.revoked_by,
        "revoked_at": snapshot.revoked_at.isoformat() if snapshot.revoked_at else None,
        "revoke_reason": snapshot.revoke_reason,
        "snapshot": snapshot.snapshot,
    }
    if items is not None:
        view["items"] = [
            {
                "item_id": it.item_id,
                "kind": it.kind,
                "ref_id": it.ref_id,
                "dimension_id": it.dimension_id,
                "seq": it.seq,
                "payload": it.payload,
            }
            for it in items
        ]
    return view


@router.get("/product-spaces/{product_space_id}/pws/readiness")
async def get_readiness(product_space_id: str, session: AsyncSession = Depends(get_session)):
    try:
        return await service.evaluate_readiness(session, product_space_id)
    except service.ProductSpaceNotFound as exc:
        raise HTTPException(status_code=404, detail="product space not found") from exc


@router.post("/product-spaces/{product_space_id}/pws/evaluate")
async def evaluate(
    product_space_id: str,
    body: ReadinessEvaluateRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await service.evaluate(session, product_space_id, body.actor)
    except service.ProductSpaceNotFound as exc:
        raise HTTPException(status_code=404, detail="product space not found") from exc


@router.post("/product-spaces/{product_space_id}/pws/freeze")
async def freeze(
    product_space_id: str,
    body: FreezeRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await service.freeze(session, product_space_id, body, body.actor)
    except service.ProductSpaceNotFound as exc:
        raise HTTPException(status_code=404, detail="product space not found") from exc
    except service.RoleNotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ReadinessNotGreen as exc:
        raise HTTPException(status_code=409, detail={"message": "pwsReadiness not green", **exc.checks}) from exc
    except service.RefreezeReasonRequired as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.RefreezeReasonInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.RefreezeNotNeeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    items = (await service.list_items(session, [result["snapshot"].pws_id])).get(
        result["snapshot"].pws_id, []
    )
    return {
        "pws": _snapshot_view(result["snapshot"], items),
        "dup_hints": result["dup_hints"],
        "dispositions": result["dispositions"],
    }


@router.post("/pws/{pws_id}/revoke")
async def revoke(pws_id: str, body: RevokeRequest, session: AsyncSession = Depends(get_session)):
    try:
        snapshot = await service.revoke(session, pws_id, body.reason, body.actor)
    except service.PwsNotFound as exc:
        raise HTTPException(status_code=404, detail="PWS not found") from exc
    except service.RoleNotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.WrongPwsState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _snapshot_view(snapshot)


@router.get("/product-spaces/{product_space_id}/pws")
async def list_versions(product_space_id: str, session: AsyncSession = Depends(get_session)):
    try:
        rows = await service.list_versions(session, product_space_id)
    except service.ProductSpaceNotFound as exc:
        raise HTTPException(status_code=404, detail="product space not found") from exc
    return [_snapshot_view(row) for row in rows]


@router.get("/pws/{pws_id}")
async def get_pws(pws_id: str, session: AsyncSession = Depends(get_session)):
    try:
        snapshot = await service.get_snapshot(session, pws_id)
    except service.PwsNotFound as exc:
        raise HTTPException(status_code=404, detail="PWS not found") from exc
    items = (await service.list_items(session, [pws_id])).get(pws_id, [])
    return _snapshot_view(snapshot, items)
