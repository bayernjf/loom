"""段3 字段池规划服务：来源路由配置、方案提交（Q12 越界）、WF-02 Gate、
候选捞回、Q13 字典管理员转正。

业务依据：PT-FP-PLAN-V2.0（06 §2.1）、Q8-Q13/Q15、line 14081/14133。
AI 不在本服务：WF-02 三维度 Skill 候选由 M10 skill7 通道接入，
M3 只接收结构化候选并做确定性校验与 Gate 流转。
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.product.fieldpool import planning
from app.product.fieldpool.models import FieldPool, FPDimension, FPSourceRoute
from app.product.fieldpool.planning import DimInput
from app.product.modeling.models import G2FieldCandidate
from app.product.product_intake.models import G2Field, ProductSpace


class ProductSpaceNotFound(Exception):
    pass


class PoolNotFound(Exception):
    pass


class DimensionNotFound(Exception):
    pass


class CandidateNotFound(Exception):
    pass


class InvalidPlan(Exception):
    pass


class GateNotAllowed(Exception):
    pass


class RouteInUse(Exception):
    pass


class FidConflict(Exception):
    pass


PLATFORM_TENANT = "_platform"


# ---------- Q8 来源路由表 ----------

async def list_routes(session: AsyncSession) -> Sequence[FPSourceRoute]:
    rows = await session.scalars(select(FPSourceRoute).order_by(FPSourceRoute.sort_order))
    return rows.all()


async def upsert_route(session, item, actor) -> FPSourceRoute:
    row = await session.get(FPSourceRoute, item.route)
    if row is None:
        row = FPSourceRoute(route=item.route)
        session.add(row)
    row.name = item.name
    row.enabled = item.enabled
    row.sort_order = item.sort_order
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="fp.route_upsert",
        entity_type="fp_source_route",
        entity_id=item.route,
        detail={"name": item.name, "enabled": item.enabled},
    )
    return row


async def delete_route(session, route: str, actor) -> None:
    row = await session.get(FPSourceRoute, route)
    if row is None:
        return
    in_use = (
        await session.scalars(
            select(FPDimension.dimension_id).where(FPDimension.source_route == route).limit(1)
        )
    ).first()
    if in_use is not None:
        raise RouteInUse(route)
    await session.delete(row)
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="fp.route_delete",
        entity_type="fp_source_route",
        entity_id=route,
    )


# ---------- 方案提交 ----------

async def submit_plan(session, product_space_id: str, body, actor) -> FieldPool:
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)

    pool = (
        await session.scalars(
            select(FieldPool).where(FieldPool.product_space_id == product_space_id)
        )
    ).first()
    if pool is not None and pool.gate != planning.GATE_REJECTED:
        raise GateNotAllowed(
            f"FieldPool is {pool.gate}; only rejected pools may be resubmitted"
        )

    if body.target_atom_min > body.target_atom_max:
        raise InvalidPlan("target_atom_min must be <= target_atom_max")

    routes = frozenset(
        r.route for r in await session.scalars(select(FPSourceRoute).where(FPSourceRoute.enabled.is_(True)))
    )
    active_fids = frozenset(
        f.fid
        for f in (
            await session.scalars(select(G2Field).where(G2Field.status == "active"))
        ).all()
    )

    dims = [
        DimInput(
            field_name=d.field_name,
            role=d.role,
            source_route=d.source_route,
            confidence=d.confidence,
            source_ref=d.source_ref,
            fid=d.fid,
            similarity=d.similarity,
            related_fid=d.related_fid,
            definition=d.definition,
        )
        for d in body.dimensions
    ]
    evaluation = planning.evaluate_plan(
        dims, sensitive=bool(ps.sensitive_industry), enabled_routes=routes, active_fids=active_fids
    )

    if pool is None:
        pool = FieldPool(tenant_id=ps.tenant_id, product_space_id=product_space_id)
        session.add(pool)
        # 清空旧维度行只发生在 rejected 重提。
    else:
        for old in await session.scalars(select(FPDimension).where(FPDimension.pool_id == pool.pool_id)):
            await session.delete(old)

    pool.gate = planning.GATE_PENDING
    pool.compliant = evaluation.compliant
    pool.violations = evaluation.violations
    pool.target_atom_min = body.target_atom_min
    pool.target_atom_max = body.target_atom_max
    pool.submitted_by = actor.id
    pool.decided_by = None
    pool.reject_reason = None
    pool.decided_at = None
    await session.flush()

    async def _persist(items, status: str):
        for order, item in enumerate(items):
            d = item.dim
            candidate_id = None
            if d.fid is None:
                # G2 候选是全局字典资产：同名候选（含他池/历史提交）复用，不重复建。
                existing = (
                    await session.scalars(
                        select(G2FieldCandidate).where(
                            G2FieldCandidate.source_layer == "wf02_dim_source",
                            G2FieldCandidate.field_name == d.field_name,
                        )
                    )
                ).first()
                if existing is not None:
                    candidate_id = existing.candidate_id
                else:
                    candidate = G2FieldCandidate(
                        tenant_id=ps.tenant_id,
                        field_name=d.field_name,
                        definition=d.definition,
                        source_layer="wf02_dim_source",
                        source_route=d.source_route,
                        confidence=d.confidence,
                        dup=item.dup,
                        related_fid=d.related_fid,
                    )
                    session.add(candidate)
                    await session.flush()
                    candidate_id = candidate.candidate_id
            session.add(
                FPDimension(
                    pool_id=pool.pool_id,
                    role=d.role,
                    source_route=d.source_route,
                    source_ref=d.source_ref or "",
                    field_name=d.field_name,
                    definition=d.definition,
                    fid=d.fid,
                    candidate_id=candidate_id,
                    confidence=d.confidence,
                    needs_detail=item.needs_detail,
                    dup=item.dup,
                    related_fid=d.related_fid,
                    status=status,
                    sort_order=order,
                )
            )

    await _persist(evaluation.selected, planning.DIM_SELECTED)
    await _persist(evaluation.backup, planning.DIM_BACKUP)

    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="fp.plan_submit",
        entity_type="field_pool",
        entity_id=pool.pool_id,
        detail={
            "selected": len(evaluation.selected),
            "backup": len(evaluation.backup),
            "violations": evaluation.violations,
            "sensitive": bool(ps.sensitive_industry),
        },
    )
    return pool


async def get_pool(session, product_space_id: str) -> FieldPool | None:
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)
    return (
        await session.scalars(
            select(FieldPool).where(FieldPool.product_space_id == product_space_id)
        )
    ).first()


async def list_dimensions(session, pool_id: str, status: str | None = None):
    stmt = select(FPDimension).where(FPDimension.pool_id == pool_id)
    if status is not None:
        stmt = stmt.where(FPDimension.status == status)
    return (await session.scalars(stmt.order_by(FPDimension.status, FPDimension.sort_order))).all()


# ---------- WF-02 HumanGate ----------

async def decide_gate(session, pool_id: str, body, actor) -> FieldPool:
    pool = await session.get(FieldPool, pool_id)
    if pool is None:
        raise PoolNotFound(pool_id)
    if pool.gate != planning.GATE_PENDING:
        raise GateNotAllowed(f"FieldPool is {pool.gate}")
    if planning.ROLE_PRODUCT_REVIEWER not in actor.roles:
        raise InvalidPlan("FieldPool Gate requires product_reviewer role")

    if body.decision == "approve":
        if not pool.compliant:
            raise GateNotAllowed(
                f"non-compliant plan must be fixed before approval: {pool.violations}"
            )
        pool.gate = planning.GATE_APPROVED
    else:
        pool.gate = planning.GATE_REJECTED
        pool.reject_reason = body.reason

    pool.decided_by = actor.id
    pool.decided_at = datetime.now(UTC)
    await append_audit(
        session,
        tenant_id=pool.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="fp.gate_" + body.decision,
        entity_type="field_pool",
        entity_id=pool.pool_id,
        detail={"reason": body.reason} if body.decision == "reject" else None,
    )
    return pool


async def restore_dimension(session, pool_id: str, dimension_id: str, actor) -> FieldPool:
    """Q12：从备选档人工捞回；selected 已满 8 时把置信度最低者挤回备选。"""
    pool = await session.get(FieldPool, pool_id)
    if pool is None:
        raise PoolNotFound(pool_id)
    if pool.gate != planning.GATE_PENDING:
        raise GateNotAllowed(f"FieldPool is {pool.gate}")

    target = await session.get(FPDimension, dimension_id)
    if target is None or target.pool_id != pool_id:
        raise DimensionNotFound(dimension_id)
    if target.status != planning.DIM_BACKUP:
        raise InvalidPlan("dimension is not in backup")

    selected = (
        await session.scalars(
            select(FPDimension)
            .where(FPDimension.pool_id == pool_id, FPDimension.status == planning.DIM_SELECTED)
            .order_by(FPDimension.sort_order)
        )
    ).all()

    bumped = None
    if len(selected) >= planning.DIM_MAX:
        bumped = min(selected, key=lambda d: d.confidence)
        bumped.status = planning.DIM_BACKUP
    target.status = planning.DIM_SELECTED
    await session.flush()

    fresh = (
        await session.scalars(
            select(FPDimension)
            .where(FPDimension.pool_id == pool_id, FPDimension.status == planning.DIM_SELECTED)
            .order_by(FPDimension.sort_order)
        )
    ).all()
    ps = await session.get(ProductSpace, pool.product_space_id)
    pool.compliant, pool.violations = _recheck_compliance(pool, fresh, bool(ps.sensitive_industry))

    await append_audit(
        session,
        tenant_id=pool.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="fp.dimension_restore",
        entity_type="fp_dimension",
        entity_id=dimension_id,
        detail={"bumped": bumped.dimension_id if bumped else None},
    )
    return pool


def _recheck_compliance(
    pool: FieldPool, selected: list[FPDimension], sensitive: bool
) -> tuple[bool, list[str]]:
    # restore 只改变维度数量/角色构成；逐条结构违规（未知来源/缺依据/非法 fid）
    # 不随捞回消失，原样保留。
    structural = {
        planning.VIOL_UNKNOWN_ROLE,
        planning.VIOL_UNKNOWN_ROUTE,
        planning.VIOL_MISSING_EVIDENCE,
        planning.VIOL_ILLEGAL_FID,
    }
    violations = [v for v in pool.violations if v in structural]
    roles = {d.role for d in selected}
    if planning.ROLE_PRODUCT_ATTRIBUTE not in roles:
        violations.append(planning.VIOL_MISSING_PRODUCT_ATTRIBUTE)
    if sensitive and planning.ROLE_RISK_CONTROL not in roles:
        violations.append(planning.VIOL_MISSING_RISK_CONTROL)
    if len(selected) < planning.DIM_MIN:
        violations.append(planning.VIOL_BELOW_MIN)
    return not violations, violations


# ---------- Q13 新字段候选转正 ----------

async def list_candidates(session, status: str | None = None):
    stmt = select(G2FieldCandidate)
    if status is not None:
        stmt = stmt.where(G2FieldCandidate.status == status)
    return (await session.scalars(stmt.order_by(G2FieldCandidate.created_at))).all()


async def promote_candidate(session, candidate_id: str, body, actor) -> G2Field:
    if planning.ROLE_DICTIONARY_ADMIN not in actor.roles:
        raise InvalidPlan("candidate promotion requires dictionary_admin role (Q13)")
    candidate = await session.get(G2FieldCandidate, candidate_id)
    if candidate is None:
        raise CandidateNotFound(candidate_id)
    if candidate.status == "approved":
        raise GateNotAllowed("candidate already promoted")

    existing = await session.get(G2Field, body.fid)
    if existing is not None:
        raise FidConflict(f"fid {body.fid} already exists in G2")

    field = G2Field(fid=body.fid, cat=body.cat, field_name=candidate.field_name, status="active")
    session.add(field)
    candidate.status = "approved"

    # 回填引用该候选的池维度，使已批准/后续 FieldPool 持合法 fid（Q68）。
    linked = await session.scalars(
        select(FPDimension).where(FPDimension.candidate_id == candidate_id)
    )
    for dim in linked.all():
        dim.fid = body.fid

    await append_audit(
        session,
        tenant_id=candidate.tenant_id or PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="fp.candidate_promote",
        entity_type="g2_field_candidate",
        entity_id=candidate_id,
        detail={"fid": body.fid, "cat": body.cat},
    )
    return field
