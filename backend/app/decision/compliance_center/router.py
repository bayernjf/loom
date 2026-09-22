from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.rbac import INTERNAL_COMPLIANCE, PermissionDenied, require_any_role
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


def require_law_domains_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    # Q118：CP-LAW 敏感领域清单读口与写口同组（docs/05 表行标 internal_compliance），
    # 补 Q109 审计遗漏的 query actor 闸：缺 actor_id 422、越权 403。
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, INTERNAL_COMPLIANCE)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


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


def _ccr_history_item(r) -> dict:
    # Q162①：历史列表紧凑视图（不带 hits，详情口再返完整 JSON）。
    return {
        "ccr_id": r.ccr_id,
        "pws_id": r.pws_id,
        "product_space_id": r.product_space_id,
        "country": r.country,
        "status": r.status,
        "block_required": r.block_required,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _ccr_detail(r) -> dict:
    item = _ccr_history_item(r)
    item["hits"] = r.hits
    item["wordlist_context"] = r.wordlist_context
    item["decided_by"] = r.decided_by
    item["decided_at"] = r.decided_at.isoformat() if r.decided_at else None
    return item


def _law_sla_view(r) -> dict:
    view = _law_view(r)
    view["created_at"] = r.created_at.isoformat() if r.created_at else None
    view.update(service.law_sla(r))
    return view


def _customer_wl_view(e) -> dict:
    # Q162③：客户侧只读词库（不返内部 entry_id 之外的管理面字段）。
    return {
        "word": e.word,
        "level": e.level,
        "action": e.action,
        "country": e.country,
        "layer": e.layer,
        "effective_from": e.effective_from.isoformat() if e.effective_from else None,
        "effective_until": e.effective_until.isoformat() if e.effective_until else None,
    }


# ---------- CP-LAW 敏感领域清单 ----------

@router.get("/api/admin/cp-law-domains")
async def list_domains(
    status: str = "active",
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_law_domains_view),
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


# ---------- Q162 客户合规风控页只读扩展（无闸，同 Q101 读口径） ----------


@router.get("/api/compliance/ccr-history")
async def ccr_history(
    tenant_id: str = Query(min_length=1),
    pws_id: str | None = None,
    country: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Q162①：该租户全部 CCR 历史（分页甲案），区别于 overview 只取每市场最新。
    rows, total = await service.list_tenant_ccr_reports(
        session,
        tenant_id=tenant_id,
        pws_id=pws_id,
        country=country,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_ccr_history_item(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/compliance/ccr/{ccr_id}")
async def ccr_detail(
    ccr_id: str,
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Q162①：单条报告详情（含 hits 完整 JSON）；按 tenant_id 收窄，越权/不存在 404。
    report = await service.get_ccr_report(session, ccr_id)
    if report is None or report.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="ccr report not found")
    return _ccr_detail(report)


@router.get("/api/compliance/law-reviews")
async def tenant_law_reviews(
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    # Q162②：租户法审记录只读，服务端派生 SLA 倒计时（不新建调度）。
    rows = await service.list_tenant_law_reviews(session, tenant_id=tenant_id)
    return [_law_sla_view(r) for r in rows]


@router.get("/api/compliance/wordlist")
async def customer_wordlist(
    level: str | None = None,
    layer: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    # Q162③：客户侧只读词库（仅 active；写口仍归 internal_compliance 管理端）。
    rows = await service.customer_wordlist(session, level=level, layer=layer)
    return [_customer_wl_view(e) for e in rows]


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
