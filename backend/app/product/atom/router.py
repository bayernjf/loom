from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.model_registry import atom_expand, gateway
from app.core.model_registry.schemas import AtomExpandInvokeRequest
from app.core.rbac import PermissionDenied
from app.product.atom import service
from app.product.atom.models import AtomCandidate, AtomConflict, ProductAtomInstance
from app.product.atom.schemas import (
    BatchApproveRequest,
    BatchSubmitRequest,
    ClusterResolveRequest,
    EvidenceRequest,
    LifecycleRequest,
    RejectRequest,
    RiskOverrideRequest,
)

router = APIRouter(prefix="/api", tags=["atom"])


def _conflict_view(c: AtomConflict) -> dict:
    return {
        "conflict_id": c.conflict_id,
        "candidate_id": c.candidate_id,
        "type": c.type,
        "status": c.status,
        "resolved_at": c.resolved_at,
    }


def _candidate_view(c: AtomCandidate, conflicts: list[AtomConflict] | None = None) -> dict:
    return {
        "candidate_id": c.candidate_id,
        "batch_id": c.batch_id,
        "product_space_id": c.product_space_id,
        "pool_id": c.pool_id,
        "dimension_id": c.dimension_id,
        "fid": c.fid,
        "content": c.content,
        "fact_type": c.fact_type,
        "risk_level": c.risk_level,
        "risk_source": c.risk_source,
        "matched_words": c.matched_words,
        "affinity": c.affinity,
        "low_affinity": c.low_affinity,
        "evidence": c.evidence,
        "evidence_due_at": c.evidence_due_at,
        "cluster_id": c.cluster_id,
        "aliases": c.aliases,
        "alias_of": c.alias_of,
        "status": c.status,
        "reject_reason": c.reject_reason,
        "approved_atom_id": c.approved_atom_id,
        "conflicts": [_conflict_view(x) for x in (conflicts or [])],
    }


def _atom_view(a: ProductAtomInstance) -> dict:
    return {
        "atom_id": a.atom_id,
        "candidate_id": a.candidate_id,
        "product_space_id": a.product_space_id,
        "pool_id": a.pool_id,
        "dimension_id": a.dimension_id,
        "fid": a.fid,
        "content": a.content,
        "fact_type": a.fact_type,
        "aliases": a.aliases,
        "risk_level": a.risk_level,
        "risk_source": a.risk_source,
        "status": a.status,
        "reference_count": a.reference_count,
    }


async def _candidate_with_conflicts(session, cand: AtomCandidate) -> dict:
    conflicts = await service.list_conflicts(session, [cand.candidate_id])
    return _candidate_view(cand, conflicts)


# ---- 拓展批次 ----

@router.post("/product-spaces/{product_space_id}/atom-batches")
async def submit_batch(
    product_space_id: str,
    body: BatchSubmitRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        batch = await service.submit_batch(session, product_space_id, body, body.actor)
        await session.commit()
    except service.ProductSpaceNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="product space not found") from exc
    except service.PoolNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="field pool not found") from exc
    except service.PoolNotApproved as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.TargetReached as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.FactAtomConflict as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.InvalidBatch as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.refresh(batch)
    candidates = await service.list_batch_candidates(session, batch.batch_id)
    conflicts = await service.list_conflicts(
        session, [c.candidate_id for c in candidates]
    )
    by_cand: dict[str, list] = {}
    for c in conflicts:
        by_cand.setdefault(c.candidate_id, []).append(c)
    return {
        "batch_id": batch.batch_id,
        "batch_size": batch.batch_size,
        "source": batch.source,
        "candidates": [
            _candidate_view(c, by_cand.get(c.candidate_id)) for c in candidates
        ],
    }


@router.post(
    "/product-spaces/{product_space_id}/atom-batches/llm-expand", status_code=201
)
async def llm_expand(
    product_space_id: str,
    body: AtomExpandInvokeRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Q86：operations 显式触发 CONFLICT-PRECHECK + ATOM-AFFINITY 双调用补池。

    不自动串链（restock_auto 留给 M8 worker）；产出整批单候选落 pending_review。
    """
    try:
        run, candidates = await atom_expand.invoke_atom_expand(
            session, product_space_id, body, body.actor
        )
    except PermissionDenied as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except atom_expand.AtomExpandInvokeNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except atom_expand.AtomExpandInvokeState as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except gateway.ModelUnavailable as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except gateway.ModelConfigError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except gateway.GenerationUpstreamError as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except atom_expand.AtomExpandOutputInvalid as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await session.commit()
    return {
        "run_id": run.run_id,
        "source": run.source,
        "model_id": run.model_id,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "candidates": [
            {"candidate_id": c.candidate_id, "state": c.state, "target_type": c.target_type}
            for c in candidates
        ],
    }


@router.get("/product-spaces/{product_space_id}/atom-candidates")
async def list_candidates(
    product_space_id: str,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = await service.list_ps_candidates(session, product_space_id, status)
    conflicts = await service.list_conflicts(session, [c.candidate_id for c in rows])
    by_cand: dict[str, list] = {}
    for c in conflicts:
        by_cand.setdefault(c.candidate_id, []).append(c)
    return [_candidate_view(c, by_cand.get(c.candidate_id)) for c in rows]


@router.get("/product-spaces/{product_space_id}/atoms")
async def list_atoms(
    product_space_id: str,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = await service.list_atoms(session, product_space_id, status)
    return [_atom_view(a) for a in rows]


# ---- Gate ----

@router.post("/atom-candidates/{candidate_id}/approve")
async def approve_candidate(
    candidate_id: str, body: LifecycleRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        atom = await service.approve_candidate(session, candidate_id, body.actor)
        await session.commit()
    except service.CandidateNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="candidate not found") from exc
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.GuardViolated as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=exc.violations) from exc
    return _atom_view(atom)


@router.post("/atom-candidates/batch-approve")
async def batch_approve(
    body: BatchApproveRequest, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    try:
        atoms = await service.approve_batch(session, body.candidate_ids, body.actor)
        await session.commit()
    except service.CandidateNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="candidate not found") from exc
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.GuardViolated as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=exc.violations) from exc
    return [_atom_view(a) for a in atoms]


@router.post("/atom-candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: str, body: RejectRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        cand = await service.reject_candidate(session, candidate_id, body.reason, body.actor)
        await session.commit()
    except service.CandidateNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="candidate not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    return await _candidate_with_conflicts(session, cand)


# ---- Q18 证据 / Q19 同义簇 / Q17 降级 ----

@router.post("/atom-candidates/{candidate_id}/evidence")
async def supplement_evidence(
    candidate_id: str, body: EvidenceRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        cand = await service.supplement_evidence(
            session, candidate_id, body.evidence, body.actor
        )
        await session.commit()
    except service.CandidateNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="candidate not found") from exc
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _candidate_with_conflicts(session, cand)


@router.post("/atom-candidates/{candidate_id}/revive")
async def revive_candidate(
    candidate_id: str, body: LifecycleRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        cand = await service.revive_candidate(session, candidate_id, body.actor)
        await session.commit()
    except service.CandidateNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="candidate not found") from exc
    except service.FactAtomConflict as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _candidate_with_conflicts(session, cand)


@router.post("/atom-clusters/{cluster_id}/resolve")
async def resolve_cluster(
    cluster_id: str, body: ClusterResolveRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        merged = await service.resolve_cluster(
            session, cluster_id, body.keeper_candidate_id, body.actor
        )
        await session.commit()
    except service.CandidateNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="cluster or keeper not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    return {"cluster_id": cluster_id, "merged": [m.candidate_id for m in merged]}


@router.post("/atom-candidates/{candidate_id}/risk-override")
async def override_risk(
    candidate_id: str, body: RiskOverrideRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        cand = await service.override_risk(
            session, candidate_id, body.level, body.reason, body.actor
        )
        await session.commit()
    except service.CandidateNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="candidate not found") from exc
    except service.GateNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.RiskOverrideForbidden as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _candidate_with_conflicts(session, cand)


# ---- 正式原子生命周期（Q20） ----

@router.post("/atoms/{atom_id}/freeze")
async def freeze_atom(
    atom_id: str, body: LifecycleRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        atom = await service.freeze_atom(session, atom_id, body.actor)
        await session.commit()
    except service.AtomNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="atom not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    return _atom_view(atom)


@router.post("/atoms/{atom_id}/unfreeze")
async def unfreeze_atom(
    atom_id: str, body: LifecycleRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        atom = await service.unfreeze_atom(session, atom_id, body.actor)
        await session.commit()
    except service.AtomNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="atom not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    return _atom_view(atom)


@router.post("/atoms/{atom_id}/compliance-suspend")
async def suspend_atom(
    atom_id: str, body: LifecycleRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        atom = await service.suspend_atom(session, atom_id, body.actor)
        await session.commit()
    except service.AtomNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="atom not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    return _atom_view(atom)


@router.post("/atoms/{atom_id}/compliance-resume")
async def resume_atom(
    atom_id: str, body: LifecycleRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        atom = await service.resume_atom(session, atom_id, body.actor)
        await session.commit()
    except service.AtomNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="atom not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    return _atom_view(atom)


@router.post("/atoms/{atom_id}/deprecate")
async def deprecate_atom(
    atom_id: str, body: LifecycleRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        atom = await service.deprecate_atom(session, atom_id, body.actor)
        await session.commit()
    except service.AtomNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="atom not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    return _atom_view(atom)


@router.post("/atoms/{atom_id}/archive")
async def archive_atom(
    atom_id: str, body: LifecycleRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        atom = await service.archive_atom(session, atom_id, body.actor)
        await session.commit()
    except service.AtomNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="atom not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    return _atom_view(atom)


@router.post("/atoms/{atom_id}/reject")
async def reject_atom(
    atom_id: str, body: RejectRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        atom = await service.reject_atom(session, atom_id, body.reason, body.actor)
        await session.commit()
    except service.AtomNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="atom not found") from exc
    except service.GateNotAllowed as exc:
        detail = str(exc)
        await session.rollback()
        raise HTTPException(
            status_code=403 if "requires" in detail else 409, detail=detail
        ) from exc
    return _atom_view(atom)
