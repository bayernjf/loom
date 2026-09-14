"""段10 合规清洗服务（WF-08）：

- COMPLIANCE：同源 Q48 词库扫描冻结快照，Q50 国家>平台>底座三层裁决（同级 Q36 从严）；
- CLAIM-DOWNGRADE：降级只产建议，人工 approval 后放行；
- LAW-REVIEW（Q49）：敏感领域自动触发 internal_compliance 法审待办，卡段11 Guard⑥；
- Q51：词表保存生效即扫 active 快照，命中出强制重冻待办（BO-07 人工执行，红线 line 7674）。

AI 通道（WF-08 三 Skill）随 M10；本切片为确定性机械判定。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.audit import append_audit
from app.core.compliance_wordlist import service as wl_service
from app.core.compliance_wordlist.models import ComplianceWordlistEntry
from app.decision.compliance_center import ccr_rules
from app.decision.compliance_center.models import (
    CcrReport,
    CpLawSensitiveDomain,
    LawReview,
)
from app.final.final_whitelist.models import FinalContentWhitelist
from app.product.modeling.models import OpsTodo
from app.product.product_intake.models import ProductSpace
from app.product.whitelist_center import pws_rules
from app.product.whitelist_center.models import PwsSnapshot

PLATFORM_TENANT = "_platform"


class DomainNotFound(Exception):
    pass


class DomainCodeTaken(Exception):
    pass


class PwsNotFound(Exception):
    pass


class WrongPwsState(Exception):
    pass


class RoleNotAllowed(Exception):
    pass


class ReportNotFound(Exception):
    pass


class ReportNotDecidable(Exception):
    pass


class LawReviewNotFound(Exception):
    pass


class LawReviewAlreadyDecided(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(dt: datetime) -> datetime:
    # SQLite 读回的时间戳不带 tz，统一按 UTC 解释。
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _require_compliance(actor) -> None:
    if ccr_rules.ROLE_INTERNAL_COMPLIANCE not in actor.roles:
        raise RoleNotAllowed("requires internal_compliance role")


# ---------- CP-LAW 敏感领域清单（Q48 独立小表，全部 CRUD + 审计） ----------

async def list_domains(session, *, status: str = "active") -> list[CpLawSensitiveDomain]:
    stmt = select(CpLawSensitiveDomain)
    if status is not None:
        stmt = stmt.where(CpLawSensitiveDomain.status == status)
    return list((await session.scalars(stmt.order_by(CpLawSensitiveDomain.code))).all())


async def create_domain(session, body, actor) -> CpLawSensitiveDomain:
    _require_compliance(actor)
    taken = (
        await session.scalars(
            select(CpLawSensitiveDomain).where(
                CpLawSensitiveDomain.code == body.item.code
            )
        )
    ).first()
    if taken is not None:
        raise DomainCodeTaken(body.item.code)
    domain = CpLawSensitiveDomain(
        code=body.item.code, name=body.item.name, created_by=actor.id
    )
    session.add(domain)
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="cplaw.domain_create",
        entity_type="cp_law_sensitive_domain",
        entity_id=domain.domain_id,
        detail={"code": domain.code},
    )
    return domain


async def update_domain(session, domain_id: str, body, actor) -> CpLawSensitiveDomain:
    _require_compliance(actor)
    domain = await session.get(CpLawSensitiveDomain, domain_id)
    if domain is None:
        raise DomainNotFound(domain_id)
    domain.code = body.item.code
    domain.name = body.item.name
    domain.status = "active"
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="cplaw.domain_update",
        entity_type="cp_law_sensitive_domain",
        entity_id=domain_id,
        detail={"code": domain.code},
    )
    return domain


async def archive_domain(session, domain_id: str, actor) -> None:
    _require_compliance(actor)
    domain = await session.get(CpLawSensitiveDomain, domain_id)
    if domain is None:
        raise DomainNotFound(domain_id)
    domain.status = "archived"
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="cplaw.domain_archive",
        entity_type="cp_law_sensitive_domain",
        entity_id=domain_id,
        detail={"code": domain.code},
    )


# ---------- Q49 法审 ----------

async def ensure_law_review(session, ps: ProductSpace, snapshot: PwsSnapshot) -> LawReview | None:
    """产品命中敏感领域清单 → 幂等建 pending 法审 + internal_compliance 待办（48h）。"""
    active_codes = {
        d.code
        for d in (
            await session.scalars(
                select(CpLawSensitiveDomain).where(
                    CpLawSensitiveDomain.status == "active"
                )
            )
        ).all()
    }
    domain = ccr_rules.match_sensitive_domain(
        ps.industry_tag, ps.sensitive_industry, active_codes
    )
    if domain is None:
        return None

    existing = (
        await session.scalars(
            select(LawReview).where(LawReview.pws_id == snapshot.pws_id)
        )
    ).first()
    if existing is not None:
        return existing

    review = LawReview(
        tenant_id=snapshot.tenant_id,
        product_space_id=snapshot.product_space_id,
        pws_id=snapshot.pws_id,
        domain=domain,
        status=ccr_rules.LAW_PENDING,
    )
    session.add(review)
    await session.flush()
    session.add(
        OpsTodo(
            tenant_id=snapshot.tenant_id,
            todo_type=ccr_rules.TODO_TYPE_LAW_REVIEW,
            entity_type="law_review",
            entity_id=review.law_review_id,
            assignee_role=ccr_rules.ROLE_INTERNAL_COMPLIANCE,
            detail={"domain": domain, "pws_id": snapshot.pws_id},
            due_at=_now() + timedelta(hours=ccr_rules.LAW_REVIEW_DUE_HOURS),
        )
    )
    await append_audit(
        session,
        tenant_id=snapshot.tenant_id,
        actor_id=None,
        actor_roles=None,
        action="ccr.law_review_triggered",
        entity_type="law_review",
        entity_id=review.law_review_id,
        detail={"domain": domain, "pws_id": snapshot.pws_id},
    )
    return review


async def decide_law_review(session, law_review_id: str, body) -> LawReview:
    _require_compliance(body.actor)
    review = await session.get(LawReview, law_review_id)
    if review is None:
        raise LawReviewNotFound(law_review_id)
    if review.status != ccr_rules.LAW_PENDING:
        raise LawReviewAlreadyDecided(law_review_id)
    review.status = ccr_rules.LAW_APPROVED if body.approved else ccr_rules.LAW_REJECTED
    review.conclusion = body.conclusion
    review.decided_by = body.actor.id
    review.decided_at = _now()

    todos = (
        await session.scalars(
            select(OpsTodo).where(
                OpsTodo.tenant_id == review.tenant_id,
                OpsTodo.todo_type == ccr_rules.TODO_TYPE_LAW_REVIEW,
                OpsTodo.entity_id == review.law_review_id,
                OpsTodo.status.in_(["open", "escalated"]),
            )
        )
    ).all()
    for todo in todos:
        todo.status = "resolved"
        todo.resolved_at = _now()
        todo.resolution = review.status
    await append_audit(
        session,
        tenant_id=review.tenant_id,
        actor_id=body.actor.id,
        actor_roles=body.actor.roles,
        action="ccr.law_review_decision",
        entity_type="law_review",
        entity_id=review.law_review_id,
        detail={"approved": body.approved, "conclusion": body.conclusion},
    )
    return review


async def list_law_reviews(session, pws_id: str) -> list[LawReview]:
    return list(
        (
            await session.scalars(
                select(LawReview)
                .where(LawReview.pws_id == pws_id)
                .order_by(LawReview.created_at)
            )
        ).all()
    )


# ---------- WF-08 合规清洗 ----------

def _snapshot_text(snapshot: PwsSnapshot) -> str:
    atoms = snapshot.snapshot.get("atoms", []) if snapshot.snapshot else []
    return " ".join(str(a.get("content", "")) for a in atoms)


async def run_ccr(session, pws_id: str, body) -> dict:
    snapshot = await session.get(PwsSnapshot, pws_id)
    if snapshot is None:
        raise PwsNotFound(pws_id)
    # 段10 只清洗冻结版本；旧版/急停版的追溯由 Q51 扫描提示，不在旧版上跑判定。
    if snapshot.status != pws_rules.PWS_FROZEN or not snapshot.is_active:
        raise WrongPwsState(f"PWS {pws_id} is {snapshot.status}, only active frozen is cleanable")
    ps = await session.get(ProductSpace, snapshot.product_space_id)

    entries = [
        e
        for e in await wl_service.active_entries(
            session, industry=ps.industry_tag, now=_now()
        )
        if ccr_rules.applicable_to_market(e, body.country)
    ]
    result = ccr_rules.evaluate(entries, _snapshot_text(snapshot))

    report = CcrReport(
        tenant_id=snapshot.tenant_id,
        product_space_id=snapshot.product_space_id,
        pws_id=pws_id,
        country=body.country,
        status=result["status"],
        block_required=result["block_required"],
        hits={"bans": result["bans"], "downgrades": result["downgrades"]},
        wordlist_context={
            "entry_ids": [e.entry_id for e in entries],
            "evaluated_at": _now().isoformat(),
            "industry": ps.industry_tag,
        },
        run_by=body.actor.id,
    )
    session.add(report)
    await session.flush()

    law_review = await ensure_law_review(session, ps, snapshot)

    await append_audit(
        session,
        tenant_id=snapshot.tenant_id,
        actor_id=body.actor.id,
        actor_roles=body.actor.roles,
        action="ccr.run",
        entity_type="ccr_report",
        entity_id=report.ccr_id,
        detail={
            "pws_id": pws_id,
            "country": body.country,
            "status": result["status"],
            "block_required": result["block_required"],
        },
    )
    return {"report": report, "law_review": law_review}


async def latest_report(
    session, pws_id: str, country: str | None
) -> CcrReport | None:
    rows = (
        await session.scalars(
            select(CcrReport)
            .where(CcrReport.pws_id == pws_id, CcrReport.country.is_(country))
            .order_by(CcrReport.created_at.desc(), CcrReport.ccr_id.desc())
        )
    ).all()
    return rows[0] if rows else None


async def approve_downgrades(session, ccr_id: str, actor) -> CcrReport:
    """CLAIM-DOWNGRADE：降级建议最终人工 approval（PT-COMPLIANCE-V2.0）。"""
    _require_compliance(actor)
    report = await session.get(CcrReport, ccr_id)
    if report is None:
        raise ReportNotFound(ccr_id)
    if report.status != ccr_rules.REPORT_DOWNGRADE_PENDING:
        raise ReportNotDecidable(f"report {ccr_id} is {report.status}, nothing to approve")
    report.status = ccr_rules.REPORT_APPROVED
    report.decided_by = actor.id
    report.decided_at = _now()
    await append_audit(
        session,
        tenant_id=report.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="ccr.downgrade_approved",
        entity_type="ccr_report",
        entity_id=ccr_id,
        detail={"suggestions": report.hits.get("downgrades", [])},
    )
    return report


async def list_reports(session, pws_id: str) -> list[CcrReport]:
    return list(
        (
            await session.scalars(
                select(CcrReport)
                .where(CcrReport.pws_id == pws_id)
                .order_by(CcrReport.created_at.desc(), CcrReport.ccr_id.desc())
            )
        ).all()
    )


async def gate_view(session, pws_id: str, country: str | None) -> dict:
    """供段11 Guard②(block_required)/Guard⑥(law_review) 消费的机械视图（M8 接入）。"""
    report = await latest_report(session, pws_id, country)
    law = (
        await session.scalars(select(LawReview).where(LawReview.pws_id == pws_id))
    ).first()
    cleaning_passed = report is not None and report.status in (
        ccr_rules.REPORT_CLEAN,
        ccr_rules.REPORT_APPROVED,
    )
    return {
        "pws_id": pws_id,
        "country": country,
        "latest_report_id": report.ccr_id if report else None,
        "report_status": report.status if report else None,
        "block_required": report.block_required if report else False,
        "cleaning_passed": cleaning_passed,
        "law_review_required": law is not None,
        "law_review_status": law.status if law else None,
        "law_review_passed": law is not None and law.status == ccr_rules.LAW_APPROVED,
    }


# ---------- Q51 词表生效即扫 ----------

async def rescan_for_entry(session, entry: ComplianceWordlistEntry) -> list[dict]:
    """词条保存生效即扫 active 冻结快照；命中产出 wordlist_hit 强制重冻待办。

    自动只"触发"Q29 强制档——重冻新版本仍须 BO-07 人工执行（红线 line 7674，
    与 M6 无全自动冻结一致）。draft FCW 随 M8 接入；段12 未发布成品随段12。
    """
    now = _now()
    if entry.status != "active":
        return []
    if entry.effective_from is not None and _as_utc(entry.effective_from) > now:
        return []
    if entry.effective_until is not None and _as_utc(entry.effective_until) < now:
        return []

    snapshots = (
        await session.scalars(
            select(PwsSnapshot).where(
                PwsSnapshot.is_active.is_(True),
                PwsSnapshot.status == pws_rules.PWS_FROZEN,
            )
        )
    ).all()
    impacted: list[dict] = []
    needle = entry.word.casefold()
    for snapshot in snapshots:
        ps = await session.get(ProductSpace, snapshot.product_space_id)
        if entry.industry is not None and entry.industry != ps.industry_tag:
            continue
        if needle not in _snapshot_text(snapshot).casefold():
            continue

        open_todo = (
            await session.scalars(
                select(OpsTodo).where(
                    OpsTodo.tenant_id == snapshot.tenant_id,
                    OpsTodo.todo_type == ccr_rules.TODO_TYPE_WORDLIST_RESCAN,
                    OpsTodo.entity_type == "pws_snapshot",
                    OpsTodo.entity_id == snapshot.pws_id,
                    OpsTodo.status.in_(["open", "escalated"]),
                )
            )
        ).first()
        todo_id = open_todo.todo_id if open_todo else None
        if open_todo is None:
            todo = OpsTodo(
                tenant_id=snapshot.tenant_id,
                todo_type=ccr_rules.TODO_TYPE_WORDLIST_RESCAN,
                entity_type="pws_snapshot",
                entity_id=snapshot.pws_id,
                assignee_role=pws_rules.ROLE_PWS_OWNER,
                detail={
                    "reason_code": ccr_rules.REASON_WORDLIST_HIT,
                    "entry_id": entry.entry_id,
                    "word": entry.word,
                    "country": entry.country,
                },
                due_at=now + timedelta(days=pws_rules.READY_TODO_DUE_DAYS),
            )
            session.add(todo)
            await session.flush()
            todo_id = todo.todo_id
            await append_audit(
                session,
                tenant_id=snapshot.tenant_id,
                actor_id=None,
                actor_roles=None,
                action="ccr.wordlist_rescan",
                entity_type="pws_snapshot",
                entity_id=snapshot.pws_id,
                detail={"entry_id": entry.entry_id, "word": entry.word},
            )
        impacted.append(
            {
                "pws_id": snapshot.pws_id,
                "product_space_id": snapshot.product_space_id,
                "tenant_id": snapshot.tenant_id,
                "version": snapshot.version,
                "country": entry.country,
                "todo_id": todo_id,
            }
        )

    # Q51：同事务扫命中快照关联的 draft FCW/未发布成品（M8 实体接入）。
    # FCW 本身无文本，骨架文本随冻结 PWS，故只看上面命中的 pws_id。
    # 【实现补】V1 全自动发证直接 published，draft 通道未开，此处置通常为空集，
    # 但实体与扫描随 M8 落地，draft 通道开启即生效。
    hit_pws_ids = [row["pws_id"] for row in impacted]
    if hit_pws_ids:
        draft_fcws = (
            await session.scalars(
                select(FinalContentWhitelist).where(
                    FinalContentWhitelist.pws_id.in_(hit_pws_ids),
                    FinalContentWhitelist.publish_status == "draft",
                )
            )
        ).all()
        for fcw in draft_fcws:
            open_fcw_todo = (
                await session.scalars(
                    select(OpsTodo).where(
                        OpsTodo.tenant_id == fcw.tenant_id,
                        OpsTodo.todo_type == ccr_rules.TODO_TYPE_WORDLIST_RESCAN,
                        OpsTodo.entity_type == "final_content_whitelist",
                        OpsTodo.entity_id == fcw.final_id,
                        OpsTodo.status.in_(["open", "escalated"]),
                    )
                )
            ).first()
            if open_fcw_todo is not None:
                continue
            todo = OpsTodo(
                tenant_id=fcw.tenant_id,
                todo_type=ccr_rules.TODO_TYPE_WORDLIST_RESCAN,
                entity_type="final_content_whitelist",
                entity_id=fcw.final_id,
                assignee_role="operations",
                detail={
                    "reason_code": ccr_rules.REASON_WORDLIST_HIT,
                    "entry_id": entry.entry_id,
                    "word": entry.word,
                    "country": entry.country,
                    "pws_id": fcw.pws_id,
                },
                due_at=now + timedelta(days=pws_rules.READY_TODO_DUE_DAYS),
            )
            session.add(todo)
            await session.flush()
            await append_audit(
                session,
                tenant_id=fcw.tenant_id,
                actor_id=None,
                actor_roles=None,
                action="ccr.wordlist_rescan",
                entity_type="final_content_whitelist",
                entity_id=fcw.final_id,
                detail={"entry_id": entry.entry_id, "word": entry.word},
            )
    return impacted
