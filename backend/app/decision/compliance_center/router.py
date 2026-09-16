from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.decision.compliance_center import service
from app.decision.compliance_center.schemas import (
    CcrRun,
    ComplianceOverview,
    DomainArchive,
    DomainUpsert,
    DowngradeApproval,
    LawDecision,
)

router = APIRouter(tags=["compliance-center"])


def _domain_view(d) -> dict:
    return {
        "domain_id": d.domain_id,
        "code": d.code,
        "name": d.name,
        "status": d.status,
    }


def _report_view(r) -> dict:
    return {
        "ccr_id": r.ccr_id,
        "pws_id": r.pws_id,
        "product_space_id": r.product_space_id,
        "country": r.country,
        "status": r.status,
        "block_required": r.block_required,
        "hits": r.hits,
        "decided_by": r.decided_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _law_view(r) -> dict:
    return {
        "law_review_id": r.law_review_id,
        "pws_id": r.pws_id,
        "product_space_id": r.product_space_id,
        "domain": r.domain,
        "status": r.status,
        "conclusion": r.conclusion,
        "decided_by": r.decided_by,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
    }


# ---------- CP-LAW 敏感领域清单 ----------

@router.get("/api/admin/cp-law-domains")
async def list_domains(
    status: str = "active", session: AsyncSession = Depends(get_session)
) -> list[dict]:
    rows = await service.list_domains(session, status=status)
    return [_domain_view(d) for d in rows]


@router.post("/api/admin/cp-law-domains")
async def create_domain(
    body: DomainUpsert, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        domain = await service.create_domain(session, body, body.actor)
        await session.commit()
    except service.RoleNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.DomainCodeTaken as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"domain code exists: {exc}") from exc
    return _domain_view(domain)


@router.put("/api/admin/cp-law-domains/{domain_id}")
async def update_domain(
    domain_id: str, body: DomainUpsert, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        domain = await service.update_domain(session, domain_id, body, body.actor)
        await session.commit()
    except service.DomainNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="domain not found") from exc
    except service.RoleNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _domain_view(domain)


@router.delete("/api/admin/cp-law-domains/{domain_id}")
async def archive_domain(
    domain_id: str, body: DomainArchive, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        await service.archive_domain(session, domain_id, body.actor)
        await session.commit()
    except service.DomainNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="domain not found") from exc
    except service.RoleNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"archived": domain_id}


# ---------- CCR 清洗 ----------

@router.get("/api/compliance/overview", response_model=ComplianceOverview)
async def compliance_overview(
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Q101：客户合规风控页租户只读聚合。读路径不触发 Q95 准入门，
    # 未知租户 200 空 items，不 writeAudit；写操作仍是 internal_compliance 台内。
    items = await service.overview_compliance(session, tenant_id=tenant_id)
    return {"items": items}


@router.post("/api/pws/{pws_id}/ccr/run")
async def run_ccr(
    pws_id: str, body: CcrRun, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        result = await service.run_ccr(session, pws_id, body)
        await session.commit()
    except service.PwsNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="pws snapshot not found") from exc
    except service.WrongPwsState as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.RoleNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "report": _report_view(result["report"]),
        "law_review": _law_view(result["law_review"]) if result["law_review"] else None,
    }


@router.get("/api/pws/{pws_id}/ccr")
async def list_ccr(
    pws_id: str, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    rows = await service.list_reports(session, pws_id)
    return [_report_view(r) for r in rows]


@router.get("/api/pws/{pws_id}/ccr/gate")
async def ccr_gate(
    pws_id: str, country: str | None = None, session: AsyncSession = Depends(get_session)
) -> dict:
    return await service.gate_view(session, pws_id, country)


@router.post("/api/ccr/{ccr_id}/approve-downgrades")
async def approve_downgrades(
    ccr_id: str, body: DowngradeApproval, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        report = await service.approve_downgrades(session, ccr_id, body.actor)
        await session.commit()
    except service.ReportNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="ccr report not found") from exc
    except service.RoleNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.ReportNotDecidable as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _report_view(report)


# ---------- 法审 Q49 ----------

@router.get("/api/pws/{pws_id}/law-reviews")
async def list_law_reviews(
    pws_id: str, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    rows = await service.list_law_reviews(session, pws_id)
    return [_law_view(r) for r in rows]


@router.post("/api/law-reviews/{law_review_id}/decision")
async def decide_law_review(
    law_review_id: str, body: LawDecision, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        review = await service.decide_law_review(session, law_review_id, body)
        await session.commit()
    except service.LawReviewNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="law review not found") from exc
    except service.RoleNotAllowed as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.LawReviewAlreadyDecided as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="law review already decided") from exc
    return _law_view(review)
