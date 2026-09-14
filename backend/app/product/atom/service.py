"""段4 字段下原子服务：拓展批次（Q14/Q15）、risk 双轨定级（Q17）、
冲突三类（line 840）、approveAtomGuard 10 项（line 2633）、同义簇（Q19）、
证据超时（Q18）、正式原子生命周期（Q20）。

WF-03 四 Skill（ATOM-EXPAND/CANON/AFFINITY/CONFLICT-PRECHECK）的 AI 通道随 M10；
M4 接收结构化候选做确定性处理。
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.audit import append_audit
from app.core.compliance_wordlist import service as wl_service
from app.product.atom import atom_rules
from app.product.atom.models import (
    AtomBatch,
    AtomCandidate,
    AtomConflict,
    ProductAtomInstance,
)
from app.product.fieldpool.models import FieldPool, FPDimension
from app.product.product_intake.models import ProductSpace


class ProductSpaceNotFound(Exception):
    pass


class PoolNotApproved(Exception):
    pass


class PoolNotFound(Exception):
    pass


class BatchNotFound(Exception):
    pass


class CandidateNotFound(Exception):
    pass


class AtomNotFound(Exception):
    pass


class InvalidBatch(Exception):
    pass


class TargetReached(Exception):
    pass


class FactAtomConflict(Exception):
    pass


class GuardViolated(Exception):
    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("approveAtomGuard failed: " + ",".join(violations))


class GateNotAllowed(Exception):
    pass


class RiskOverrideForbidden(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


PLATFORM_TENANT = "_platform"


# ---------- 拓展批次提交 ----------

async def submit_batch(session, product_space_id: str, body, actor) -> AtomBatch:
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)

    pool = (
        await session.scalars(
            select(FieldPool).where(FieldPool.product_space_id == product_space_id)
        )
    ).first()
    if pool is None:
        raise PoolNotFound(product_space_id)
    if pool.gate != "approved":
        raise PoolNotApproved("atoms expand only under an approved FieldPool")

    batch_size = body.batch_size or atom_rules.default_batch_size(
        sensitive=bool(ps.sensitive_industry)
    )
    if len(body.items) > batch_size:
        raise InvalidBatch(
            f"batch has {len(body.items)} items, exceeding batch size {batch_size} (Q14)"
        )

    if body.source == "ai":
        approved_count = await _approved_atom_count(session, product_space_id)
        if atom_rules.target_reached(approved_count, pool.target_atom_max):
            raise TargetReached(
                f"approved atoms {approved_count} reached target {pool.target_atom_max} (Q15)"
            )

    # 维度归属校验：必须属于本池且为 selected（approveAtomGuard② 的提交期前置）。
    dim_ids = {item.dimension_id for item in body.items}
    dims = {
        d.dimension_id: d
        for d in (
            await session.scalars(
                select(FPDimension).where(
                    FPDimension.pool_id == pool.pool_id,
                    FPDimension.dimension_id.in_(dim_ids),
                )
            )
        ).all()
    }
    for dim_id in dim_ids:
        dim = dims.get(dim_id)
        if dim is None or dim.status != "selected":
            raise InvalidBatch(f"dimension {dim_id} is not a selected dimension of the pool")

    # PT-ATOM-EXP：同批次去重。
    seen: set[str] = set()
    for item in body.items:
        norm = atom_rules.normalize_text(item.content)
        if norm in seen:
            raise InvalidBatch(f"duplicate atom content within batch: {item.content}")
        seen.add(norm)

    # line 11189：产品事实原子引用数恒=1，跨产品查重（候选+正式实例，merged/archived 除外）。
    for item in body.items:
        if item.fact_type is not None and await _fact_value_exists(
            session, atom_rules.normalize_text(item.content)
        ):
            raise FactAtomConflict(
                f"product-fact atom value already exists: {item.content} ({item.fact_type})"
            )

    entries = await wl_service.active_entries(
        session, industry=ps.industry_tag, now=_now()
    )

    batch = AtomBatch(
        tenant_id=ps.tenant_id,
        product_space_id=product_space_id,
        pool_id=pool.pool_id,
        batch_size=batch_size,
        source=body.source,
        sensitive_snapshot=bool(ps.sensitive_industry),
        submitted_by=actor.id,
    )
    session.add(batch)
    await session.flush()

    for item in body.items:
        dim = dims[item.dimension_id]
        hits = wl_service.match_words(item.content, entries)
        grade = atom_rules.grade_risk(item.content, item.ai_risk, hits)
        has_evidence = bool((item.evidence or "").strip())
        status = (
            atom_rules.CAND_PENDING_REVIEW
            if has_evidence
            else atom_rules.CAND_PENDING_EVIDENCE
        )
        due = (
            None
            if has_evidence
            else _now() + timedelta(days=atom_rules.evidence_timeout_days())
        )
        candidate = AtomCandidate(
            tenant_id=ps.tenant_id,
            batch_id=batch.batch_id,
            product_space_id=product_space_id,
            pool_id=pool.pool_id,
            dimension_id=item.dimension_id,
            fid=dim.fid,
            content=item.content,
            normalized=atom_rules.normalize_text(item.content),
            fact_type=item.fact_type,
            risk_level=grade.level,
            risk_source=grade.source,
            matched_words=[{"word": h.word, "level": h.level, "action": h.action} for h in grade.hits],
            affinity=item.affinity,
            low_affinity=atom_rules.is_low_affinity(item.affinity),
            evidence=item.evidence,
            evidence_due_at=due,
            cluster_id=item.cluster_id,
            status=status,
            submitted_by=actor.id,
        )
        session.add(candidate)
        await session.flush()
        for ctype, cstatus in atom_rules.conflicts_for(grade, has_evidence=has_evidence):
            session.add(
                AtomConflict(
                    candidate_id=candidate.candidate_id,
                    type=ctype,
                    status=cstatus,
                    detail={"risk_level": grade.level, "risk_source": grade.source},
                )
            )

    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="atom.batch_submit",
        entity_type="atom_batch",
        entity_id=batch.batch_id,
        detail={
            "items": len(body.items),
            "batch_size": batch_size,
            "source": body.source,
            "pool_id": pool.pool_id,
        },
    )
    return batch


async def _approved_atom_count(session, product_space_id: str) -> int:
    rows = await session.scalars(
        select(ProductAtomInstance.atom_id).where(
            ProductAtomInstance.product_space_id == product_space_id,
            ProductAtomInstance.status.in_(
                [atom_rules.ATOM_APPROVED, atom_rules.ATOM_FROZEN]
            ),
        )
    )
    return len(rows.all())


async def _fact_value_exists(session, normalized: str) -> bool:
    """line 11189：事实原子值全局唯一（跨产品/跨租户严禁复用）。"""
    live_candidate_statuses = [
        atom_rules.CAND_PENDING_REVIEW,
        atom_rules.CAND_PENDING_EVIDENCE,
        atom_rules.CAND_APPROVED,
    ]
    c_rows = await session.scalars(
        select(AtomCandidate.candidate_id).where(
            AtomCandidate.normalized == normalized,
            AtomCandidate.fact_type.is_not(None),
            AtomCandidate.status.in_(live_candidate_statuses),
        )
    )
    if c_rows.first() is not None:
        return True
    a_rows = await session.scalars(
        select(ProductAtomInstance.atom_id).where(
            ProductAtomInstance.normalized == normalized,
            ProductAtomInstance.fact_type.is_not(None),
            ProductAtomInstance.status != atom_rules.ATOM_ARCHIVED,
        )
    )
    return a_rows.first() is not None


# ---------- 查询 ----------

async def list_batch_candidates(session, batch_id: str) -> Sequence[AtomCandidate]:
    batch = await session.get(AtomBatch, batch_id)
    if batch is None:
        raise BatchNotFound(batch_id)
    return (
        await session.scalars(
            select(AtomCandidate)
            .where(AtomCandidate.batch_id == batch_id)
            .order_by(AtomCandidate.created_at)
        )
    ).all()


async def list_ps_candidates(
    session, product_space_id: str, status: str | None = None
) -> Sequence[AtomCandidate]:
    stmt = select(AtomCandidate).where(
        AtomCandidate.product_space_id == product_space_id
    )
    if status is not None:
        stmt = stmt.where(AtomCandidate.status == status)
    return (
        await session.scalars(stmt.order_by(AtomCandidate.created_at))
    ).all()


async def list_atoms(
    session, product_space_id: str, status: str | None = None
) -> Sequence[ProductAtomInstance]:
    stmt = select(ProductAtomInstance).where(
        ProductAtomInstance.product_space_id == product_space_id
    )
    if status is not None:
        stmt = stmt.where(ProductAtomInstance.status == status)
    return (await session.scalars(stmt.order_by(ProductAtomInstance.created_at))).all()


async def _open_conflict_types(session, candidate_id: str) -> set[str]:
    rows = await list_conflicts(session, [candidate_id], open_only=True)
    return {c.type for c in rows}


async def list_conflicts(
    session, candidate_ids: list[str], *, open_only: bool = False
) -> Sequence[AtomConflict]:
    stmt = select(AtomConflict).where(AtomConflict.candidate_id.in_(candidate_ids))
    if open_only:
        stmt = stmt.where(AtomConflict.resolved_at.is_(None))
    return (await session.scalars(stmt)).all()


# ---------- approveAtomGuard ----------

async def approve_candidate(
    session, candidate_id: str, actor, *, bulk: bool = False
) -> ProductAtomInstance:
    cand = await session.get(AtomCandidate, candidate_id)
    if cand is None:
        raise CandidateNotFound(candidate_id)
    if atom_rules.ROLE_REVIEWER not in actor.roles:
        raise GateNotAllowed("atom Gate requires product_reviewer role")

    pool = await session.get(FieldPool, cand.pool_id)
    violations = atom_rules.approve_guard_checks(
        candidate_ps_id=cand.product_space_id,
        expected_ps_id=pool.product_space_id,
        candidate_pool_id=cand.pool_id,
        expected_pool_id=pool.pool_id,
        pool_gate=pool.gate,
        candidate_status=cand.status,
        conflict_types=await _open_conflict_types(session, candidate_id),
        approved_atom_id=cand.approved_atom_id,
        has_evidence=bool((cand.evidence or "").strip()),
        bulk=bulk,
        risk_level=cand.risk_level,
    )
    if violations:
        raise GuardViolated(violations)

    # Q19：keeper 通过时，同簇 merged 候选文本进 aliases（不删，供生成同义替换）。
    aliases = list(cand.aliases)
    merged = await session.scalars(
        select(AtomCandidate).where(
            AtomCandidate.alias_of == candidate_id,
            AtomCandidate.status == atom_rules.CAND_MERGED,
        )
    )
    for m in merged.all():
        aliases.append(m.content)

    atom = ProductAtomInstance(
        tenant_id=cand.tenant_id,
        product_space_id=cand.product_space_id,
        pool_id=cand.pool_id,
        candidate_id=cand.candidate_id,
        dimension_id=cand.dimension_id,
        fid=cand.fid,
        content=cand.content,
        normalized=cand.normalized,
        fact_type=cand.fact_type,
        aliases=aliases,
        risk_level=cand.risk_level,
        risk_source=cand.risk_source,
        affinity=cand.affinity,
        evidence=cand.evidence,
        status=atom_rules.ATOM_APPROVED,
        created_by=actor.id,
    )
    session.add(atom)
    cand.status = atom_rules.CAND_APPROVED
    cand.decided_by = actor.id
    cand.decided_at = _now()
    await session.flush()
    cand.approved_atom_id = atom.atom_id

    await _resolve_conflicts(session, candidate_id)

    await append_audit(  # ⑩变更前 writeAudit（Gate 留痕先于正式化生效）
        session,
        tenant_id=cand.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="atom.approve",
        entity_type="atom_candidate",
        entity_id=candidate_id,
        detail={
            "atom_id": atom.atom_id,
            "risk_level": cand.risk_level,
            "risk_source": cand.risk_source,
            "bulk": bulk,
            "aliases": len(aliases),
        },
    )
    return atom


async def approve_batch(session, candidate_ids: list[str], actor) -> list[ProductAtomInstance]:
    """批量 Gate（Q70）：high/critical 禁批量；任一 Guard 失败整批 409（事务回滚）。"""
    if atom_rules.ROLE_REVIEWER not in actor.roles:
        raise GateNotAllowed("atom Gate requires product_reviewer role")
    atoms = []
    for cid in candidate_ids:
        atoms.append(await approve_candidate(session, cid, actor, bulk=True))
    await append_audit(
        session,
        tenant_id=atoms[0].tenant_id if atoms else PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="atom.batch_approve",
        entity_type="atom_batch_gate",
        entity_id=",".join(candidate_ids),
        detail={"count": len(candidate_ids)},
    )
    return atoms


async def reject_candidate(session, candidate_id: str, reason: str, actor) -> AtomCandidate:
    cand = await session.get(AtomCandidate, candidate_id)
    if cand is None:
        raise CandidateNotFound(candidate_id)
    if atom_rules.ROLE_REVIEWER not in actor.roles:
        raise GateNotAllowed("atom Gate requires product_reviewer role")
    if cand.status not in (
        atom_rules.CAND_PENDING_REVIEW,
        atom_rules.CAND_PENDING_EVIDENCE,
    ):
        raise GateNotAllowed(f"candidate is {cand.status}")

    action = "atom.reject"
    open_types = await _open_conflict_types(session, candidate_id)
    if atom_rules.CONFLICT_DISABLED_EXPRESSION in open_types:
        # critical 禁用表达：驳回 + 合规审计（line 840）。
        action = "atom.reject_disabled_expression"

    cand.status = atom_rules.CAND_REJECTED
    cand.reject_reason = reason
    cand.decided_by = actor.id
    cand.decided_at = _now()
    await append_audit(
        session,
        tenant_id=cand.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action=action,
        entity_type="atom_candidate",
        entity_id=candidate_id,
        detail={"reason": reason, "conflicts": sorted(open_types)},
    )
    return cand


# ---------- Q18 证据 ----------

async def supplement_evidence(session, candidate_id: str, evidence: str, actor) -> AtomCandidate:
    cand = await session.get(AtomCandidate, candidate_id)
    if cand is None:
        raise CandidateNotFound(candidate_id)
    if cand.status != atom_rules.CAND_PENDING_EVIDENCE:
        raise GateNotAllowed(f"candidate is {cand.status}, not pending_evidence")
    cand.evidence = evidence
    cand.status = atom_rules.CAND_PENDING_REVIEW
    cand.evidence_due_at = None
    # high 补证据后 evidence_required 冲突解除；disabled_expression 不解。
    conflicts = (
        await session.scalars(
            select(AtomConflict).where(
                AtomConflict.candidate_id == candidate_id,
                AtomConflict.resolved_at.is_(None),
            )
        )
    ).all()
    for c in conflicts:
        if c.type == atom_rules.CONFLICT_EVIDENCE_REQUIRED:
            c.resolved_at = _now()
    await append_audit(
        session,
        tenant_id=cand.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="atom.evidence_supplement",
        entity_type="atom_candidate",
        entity_id=candidate_id,
    )
    return cand


async def revive_candidate(session, candidate_id: str, actor) -> AtomCandidate:
    """Q18：证据超时自动驳回可复活重提（重新审核）。"""
    cand = await session.get(AtomCandidate, candidate_id)
    if cand is None:
        raise CandidateNotFound(candidate_id)
    if cand.status != atom_rules.CAND_REJECTED:
        raise GateNotAllowed("only rejected candidates can be revived")
    if cand.reject_reason != atom_rules.REJECT_EVIDENCE_TIMEOUT:
        raise GateNotAllowed("only evidence-timeout rejections are revivable (Q18)")
    if cand.fact_type is not None:
        # line 11189：复活前若同款事实原子值已在别处存活，不得再进审核。
        other_live = await _fact_value_exists(session, cand.normalized)
        if other_live:
            raise FactAtomConflict(
                f"product-fact atom value already exists elsewhere: {cand.content}"
            )
    cand.status = (
        atom_rules.CAND_PENDING_REVIEW
        if (cand.evidence or "").strip()
        else atom_rules.CAND_PENDING_EVIDENCE
    )
    if cand.status == atom_rules.CAND_PENDING_EVIDENCE:
        cand.evidence_due_at = _now() + timedelta(
            days=atom_rules.evidence_timeout_days()
        )
    cand.reject_reason = None
    cand.decided_by = None
    cand.decided_at = None
    await append_audit(
        session,
        tenant_id=cand.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="atom.revive",
        entity_type="atom_candidate",
        entity_id=candidate_id,
    )
    return cand


async def sweep_evidence_timeouts(session, now: datetime) -> int:
    """Q18：pending_evidence 挂满 7 天自动驳回（理由=证据超时）。调度器 M10 接。"""
    due = (
        await session.scalars(
            select(AtomCandidate).where(
                AtomCandidate.status == atom_rules.CAND_PENDING_EVIDENCE,
                AtomCandidate.evidence_due_at.is_not(None),
                AtomCandidate.evidence_due_at <= now,
            )
        )
    ).all()
    for cand in due:
        cand.status = atom_rules.CAND_REJECTED
        cand.reject_reason = atom_rules.REJECT_EVIDENCE_TIMEOUT
        cand.decided_at = now
        await append_audit(
            session,
            tenant_id=cand.tenant_id,
            actor_id=None,
            actor_roles=None,
            action="atom.evidence_timeout",
            entity_type="atom_candidate",
            entity_id=cand.candidate_id,
        )
    return len(due)


# ---------- Q19 同义词簇 ----------

async def resolve_cluster(
    session, cluster_id: str, keeper_candidate_id: str, actor
) -> list[AtomCandidate]:
    members = (
        await session.scalars(
            select(AtomCandidate).where(AtomCandidate.cluster_id == cluster_id)
        )
    ).all()
    if not members:
        raise CandidateNotFound(cluster_id)
    if atom_rules.ROLE_REVIEWER not in actor.roles:
        raise GateNotAllowed("cluster resolution requires product_reviewer role")
    keeper = next((m for m in members if m.candidate_id == keeper_candidate_id), None)
    if keeper is None:
        raise CandidateNotFound(keeper_candidate_id)

    merged = []
    for m in members:
        if m.candidate_id == keeper_candidate_id:
            continue
        if m.status not in (
            atom_rules.CAND_PENDING_REVIEW,
            atom_rules.CAND_PENDING_EVIDENCE,
        ):
            raise GateNotAllowed(
                f"cluster member {m.candidate_id} is {m.status}, cannot merge"
            )
        m.status = atom_rules.CAND_MERGED
        m.alias_of = keeper_candidate_id
        m.decided_by = actor.id
        m.decided_at = _now()
        merged.append(m)
    await append_audit(
        session,
        tenant_id=keeper.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="atom.cluster_resolve",
        entity_type="atom_cluster",
        entity_id=cluster_id,
        detail={"keeper": keeper_candidate_id, "merged": [m.candidate_id for m in merged]},
    )
    return merged


# ---------- Q17 人工复核降级 ----------

async def override_risk(session, candidate_id: str, level: str, reason: str, actor) -> AtomCandidate:
    cand = await session.get(AtomCandidate, candidate_id)
    if cand is None:
        raise CandidateNotFound(candidate_id)
    if atom_rules.ROLE_REVIEWER not in actor.roles:
        raise GateNotAllowed("risk override requires product_reviewer role")
    # 词表强制定级 AI/系统无权改；人工降级只对 AI 判级开放（Q17）。
    if cand.risk_source == "wordlist":
        raise RiskOverrideForbidden("wordlist-graded risk cannot be overridden (Q17)")
    old = cand.risk_level
    cand.risk_level = level
    cand.risk_source = "manual"
    if cand.status in (
        atom_rules.CAND_PENDING_REVIEW,
        atom_rules.CAND_PENDING_EVIDENCE,
    ):
        # 降级离开 high：单条审/证据冲突解除（重建确定性冲突集）。
        conflicts = (
            await session.scalars(
                select(AtomConflict).where(
                    AtomConflict.candidate_id == candidate_id,
                    AtomConflict.resolved_at.is_(None),
                )
            )
        ).all()
        has_evidence = bool((cand.evidence or "").strip())
        wanted = {t for t, _ in atom_rules.conflicts_for(
            atom_rules.RiskGrade(level=level, source="manual"), has_evidence=has_evidence
        )}
        for c in conflicts:
            if c.type not in wanted:
                c.resolved_at = _now()
        for ctype, cstatus in wanted - {c.type for c in conflicts}:
            session.add(
                AtomConflict(
                    candidate_id=candidate_id, type=ctype, status=cstatus,
                    detail={"risk_level": level, "risk_source": "manual"},
                )
            )
    await append_audit(
        session,
        tenant_id=cand.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="atom.risk_override",
        entity_type="atom_candidate",
        entity_id=candidate_id,
        detail={"from": old, "to": level, "reason": reason},
    )
    return cand


# ---------- 正式原子生命周期（Q20） ----------

async def _get_atom(session, atom_id: str) -> ProductAtomInstance:
    atom = await session.get(ProductAtomInstance, atom_id)
    if atom is None:
        raise AtomNotFound(atom_id)
    return atom


def _require_role(actor, role: str):
    if role not in actor.roles:
        raise GateNotAllowed(f"this action requires {role} role")


async def _transition(
    session, atom, *, from_statuses: set[str], to_status: str, role: str, action: str, actor
) -> ProductAtomInstance:
    _require_role(actor, role)
    if atom.status not in from_statuses:
        raise GateNotAllowed(f"atom is {atom.status}, expected one of {sorted(from_statuses)}")
    atom.status = to_status
    atom.status_changed_at = _now()
    await append_audit(
        session,
        tenant_id=atom.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action=action,
        entity_type="product_atom_instance",
        entity_id=atom.atom_id,
        detail={"from": sorted(from_statuses), "to": to_status},
    )
    return atom


async def freeze_atom(session, atom_id: str, actor) -> ProductAtomInstance:
    atom = await _get_atom(session, atom_id)
    return await _transition(
        session, atom,
        from_statuses={atom_rules.ATOM_APPROVED},
        to_status=atom_rules.ATOM_FROZEN,
        role=atom_rules.ROLE_OPERATIONS, action="atom.freeze", actor=actor,
    )  # Q20：冻结=运营


async def unfreeze_atom(session, atom_id: str, actor) -> ProductAtomInstance:
    atom = await _get_atom(session, atom_id)
    return await _transition(
        session, atom,
        from_statuses={atom_rules.ATOM_FROZEN},
        to_status=atom_rules.ATOM_APPROVED,
        role=atom_rules.ROLE_OPERATIONS, action="atom.unfreeze", actor=actor,
    )  # Q20：解冻=运营，解冻不重审


async def suspend_atom(session, atom_id: str, actor) -> ProductAtomInstance:
    atom = await _get_atom(session, atom_id)
    return await _transition(
        session, atom,
        from_statuses={atom_rules.ATOM_APPROVED, atom_rules.ATOM_FROZEN},
        to_status=atom_rules.ATOM_COMPLIANCE_SUSPENDED,
        role=atom_rules.ROLE_COMPLIANCE, action="atom.compliance_suspend", actor=actor,
    )  # Q20：合规暂停=合规角色触发


async def resume_atom(session, atom_id: str, actor) -> ProductAtomInstance:
    atom = await _get_atom(session, atom_id)
    return await _transition(
        session, atom,
        from_statuses={atom_rules.ATOM_COMPLIANCE_SUSPENDED},
        to_status=atom_rules.ATOM_APPROVED,
        role=atom_rules.ROLE_COMPLIANCE, action="atom.compliance_resume", actor=actor,
    )  # Q20：恢复须合规角色复核


async def reject_atom(session, atom_id: str, reason: str, actor) -> ProductAtomInstance:
    """13 §1.3：已通过→已驳回（产品审核员）。"""
    atom = await _get_atom(session, atom_id)
    _require_role(actor, atom_rules.ROLE_REVIEWER)
    if atom.status not in {atom_rules.ATOM_APPROVED, atom_rules.ATOM_FROZEN}:
        raise GateNotAllowed(f"atom is {atom.status}")
    atom.status = atom_rules.ATOM_REJECTED
    atom.status_changed_at = _now()
    await append_audit(
        session,
        tenant_id=atom.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="atom.formal_reject",
        entity_type="product_atom_instance",
        entity_id=atom.atom_id,
        detail={"reason": reason},
    )
    return atom


async def deprecate_atom(session, atom_id: str, actor) -> ProductAtomInstance:
    """Q20：废弃；恢复=视同新原子重走审核（不做原地复活端点）。"""
    atom = await _get_atom(session, atom_id)
    _require_role(actor, atom_rules.ROLE_OPERATIONS)
    if atom.status not in {atom_rules.ATOM_APPROVED, atom_rules.ATOM_FROZEN}:
        raise GateNotAllowed(f"atom is {atom.status}")
    atom.status = atom_rules.ATOM_DEPRECATED
    atom.status_changed_at = _now()
    await append_audit(
        session,
        tenant_id=atom.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="atom.deprecate",
        entity_type="product_atom_instance",
        entity_id=atom.atom_id,
    )
    return atom


async def archive_atom(session, atom_id: str, actor) -> ProductAtomInstance:
    atom = await _get_atom(session, atom_id)
    _require_role(actor, atom_rules.ROLE_OPERATIONS)
    if atom.status not in {atom_rules.ATOM_DEPRECATED, atom_rules.ATOM_REJECTED}:
        raise GateNotAllowed("only deprecated/rejected atoms can be archived")
    atom.status = atom_rules.ATOM_ARCHIVED
    atom.status_changed_at = _now()
    await append_audit(
        session,
        tenant_id=atom.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="atom.archive",
        entity_type="product_atom_instance",
        entity_id=atom.atom_id,
    )
    return atom


async def _resolve_conflicts(session, candidate_id: str) -> None:
    conflicts = (
        await session.scalars(
            select(AtomConflict).where(
                AtomConflict.candidate_id == candidate_id,
                AtomConflict.resolved_at.is_(None),
            )
        )
    ).all()
    for c in conflicts:
        c.resolved_at = _now()
