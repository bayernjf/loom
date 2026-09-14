"""skill7 通道 HTTP 端点（前缀 /api；05 §1.4 切片 e，Q76）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.rbac import PermissionDenied
from app.core.skill7 import registry, service
from app.core.skill7.models import SkillCandidate, SkillRun
from app.core.skill7.schemas import CandidateDecisionRequest, DeliverRunRequest
from app.product.product_intake.service import IntakeNotFound

router = APIRouter(prefix="/api", tags=["skill7"])


def _run_view(run: SkillRun) -> dict:
    return {
        "run_id": run.run_id,
        "skill_id": run.skill_id,
        "wf_id": run.wf_id,
        "tenant_id": run.tenant_id,
        "product_space_id": run.product_space_id,
        "intake_id": run.intake_id,
        "status": run.status,
        "source": run.source,
        "input": run.input_payload,
        "output": run.output_payload,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "confidence": run.confidence,
        "error": run.error,
        "created_by": run.created_by,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _candidate_view(cand: SkillCandidate) -> dict:
    return {
        "candidate_id": cand.candidate_id,
        "run_id": cand.run_id,
        "candidate_index": cand.candidate_index,
        "skill_id": cand.skill_id,
        "wf_id": cand.wf_id,
        "tenant_id": cand.tenant_id,
        "product_space_id": cand.product_space_id,
        "intake_id": cand.intake_id,
        "target_type": cand.target_type,
        "payload": cand.payload,
        "state": cand.state,
        "applied_refs": cand.applied_refs,
        "human_modified": cand.human_modified,
        "review_note": cand.review_note,
        "reviewed_by": cand.reviewed_by,
        "reviewed_at": cand.reviewed_at.isoformat() if cand.reviewed_at else None,
        "created_at": cand.created_at.isoformat() if cand.created_at else None,
    }


@router.post("/skill-runs")
async def deliver_run(
    body: DeliverRunRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        run, candidates = await service.deliver_run(session, body)
        await session.commit()
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ProductSpaceMissing as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="product space not found") from exc
    except IntakeNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="intake not found") from exc
    except registry.RegistryError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=f"unregistered skill/workflow: {exc}") from exc
    except service.InvalidCandidatePayload as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"run": _run_view(run), "candidate_ids": [c.candidate_id for c in candidates]}


@router.get("/skill-runs")
async def list_runs(
    product_space_id: str | None = None,
    intake_id: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = await service.list_runs(
        session,
        product_space_id=product_space_id,
        intake_id=intake_id,
        status=status,
    )
    return {"runs": [_run_view(r) for r in rows]}


@router.get("/skill-runs/{run_id}")
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    run = await session.get(SkillRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="skill run not found")
    return _run_view(run)


@router.get("/skill-candidates")
async def list_candidates(
    product_space_id: str | None = None,
    intake_id: str | None = None,
    state: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = await service.list_candidates(
        session,
        product_space_id=product_space_id,
        intake_id=intake_id,
        state=state,
    )
    return {"candidates": [_candidate_view(c) for c in rows]}


@router.post("/skill-candidates/{candidate_id}/decision")
async def decide_candidate(
    candidate_id: str,
    body: CandidateDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.product.atom import service as atom_service
    from app.product.condition import service as pwc_service
    from app.product.fieldpool import service as fp_service
    from app.product.modeling import service as modeling_service

    try:
        cand = await service.decide_candidate(session, candidate_id, body)
        await session.commit()
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.CandidateMissing as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="skill candidate not found") from exc
    except service.CandidateNotReviewable as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.InvalidCandidatePayload as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except registry.RegistryError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=f"workflow gate misconfigured: {exc}") from exc
    # 适配器复用既有业务服务，错误口径与各业务端点一致。
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
    # c1_recognition 适配器（Q79）：口径与 /api/intakes/{id}/c1-recognition 一致。
    except IntakeNotFound:
        await session.rollback()
        raise HTTPException(status_code=404, detail="intake not found")
    except modeling_service.RecognitionNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (modeling_service.ConfigError, modeling_service.InvalidDecision) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # atom_batch 适配器（Q80）：口径与 POST /api/product-spaces/{id}/atom-batches 一致。
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
    return _candidate_view(cand)
