"""统一审核工作台 HTTP 端点（Q70 一期，Q93；前缀 /api/review-workbench）。

actor 口径同 Q92 管理面 GET：query actor_id 必填（缺 422）、roles 可重复，
FastAPI 依赖把 PermissionDenied 映射 403；真实会话/JWT 中间件随 V2。
可见角色 = 注册表全部 WF 的 skill7 Gate 角色并集（当前 operations+
product_reviewer，数据驱动）；批量通过逐条另过所属 WF Gate 角色。
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.rbac import PermissionDenied, require_any_role
from app.core.skill7.router import _candidate_view
from app.core.workbench import service
from app.core.workbench.schemas import BatchApproveRequest
from app.product.atom import service as atom_service
from app.product.condition import service as pwc_service
from app.product.fieldpool import service as fp_service
from app.product.modeling import service as modeling_service
from app.product.product_intake.service import IntakeNotFound

router = APIRouter(prefix="/api/review-workbench", tags=["review-workbench"])

TargetTypeFilter = Literal[
    "pwc_combo", "field_plan", "c1_recognition", "atom_batch", "c7_layer4"
]
StateFilter = Literal["pending_review", "applied", "archived"]
RiskFilter = Literal["critical", "high", "medium", "low"]


def require_workbench_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, *service.queue_roles())
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


@router.get("/candidates")
async def list_queue(
    state: StateFilter = "pending_review",
    target_type: list[TargetTypeFilter] = Query(default=None),
    wf_id: str | None = None,
    risk_level: RiskFilter | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_workbench_view),
) -> dict:
    return await service.list_queue(
        session,
        state=state,
        target_types=list(target_type) if target_type else None,
        wf_id=wf_id,
        risk_level=risk_level,
        limit=limit,
        offset=offset,
    )


@router.post("/batch-approve")
async def batch_approve(
    body: BatchApproveRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        applied = await service.batch_approve(
            session,
            candidate_ids=body.candidate_ids,
            reason=body.reason,
            actor=body.actor,
        )
        await session.commit()
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.WorkbenchCandidateMissing as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=f"candidate(s) not found: {exc}") from exc
    except service.BatchCandidateNotPending as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.BatchGateRejected as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 适配器错误口径与 POST /api/skill-candidates/{id}/decision 完全一致。
    except pwc_service.ProductSpaceNotFound:
        await session.rollback()
        raise HTTPException(status_code=404, detail="product space not found")
    except pwc_service.PoolNotApproved as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except pwc_service.InvalidFunnel as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except fp_service.ProductSpaceNotFound:
        await session.rollback()
        raise HTTPException(status_code=404, detail="product space not found")
    except fp_service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except fp_service.InvalidPlan as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntakeNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="intake not found") from exc
    except modeling_service.RecognitionNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (modeling_service.ConfigError, modeling_service.InvalidDecision) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (atom_service.ProductSpaceNotFound, atom_service.PoolNotFound) as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        atom_service.PoolNotApproved,
        atom_service.TargetReached,
        atom_service.FactAtomConflict,
    ) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except atom_service.InvalidBatch as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except modeling_service.CategoryNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="category not found") from exc
    except modeling_service.c7.IllegalFid as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "approved": [_candidate_view(cand) for cand in applied],
        "count": len(applied),
    }
