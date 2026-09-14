"""段6 PWS 冻结服务：就绪门（line 2634）、Q28 待办、Q29/Q30/Q31/Q32 版本动作、Q33 同租户查重提示。

AI 不参与冻结：系统只做机械核验与待办提请，盖章必须 BO-07（whitelist_owner，红线 line 7674）。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.audit import append_audit
from app.product.atom.atom_rules import ATOM_APPROVED
from app.product.atom.models import AtomCandidate, AtomConflict, ProductAtomInstance
from app.product.condition import pwc_rules
from app.product.condition.models import ConditionPackage, PwcComboItem
from app.product.fieldpool.models import FieldPool
from app.product.modeling.models import OpsTodo
from app.product.product_intake.models import ProductSpace
from app.product.whitelist_center import pws_rules
from app.product.whitelist_center.models import (
    PwsFreezeLog,
    PwsSnapshot,
    PwsSnapshotItem,
)

TODO_TYPE_PWS_READY = "pws_ready"
ENTITY_PS = "product_space"
_ACTIVE_PWC_STATUSES = (pwc_rules.PWC_READY, "used")


class ProductSpaceNotFound(Exception):
    pass


class PwsNotFound(Exception):
    pass


class ReadinessNotGreen(Exception):
    def __init__(self, checks: dict):
        self.checks = checks
        super().__init__("pwsReadiness gates are not all green")


class RefreezeReasonRequired(Exception):
    pass


class RefreezeNotNeeded(Exception):
    pass


class RefreezeReasonInvalid(Exception):
    pass


class WrongPwsState(Exception):
    pass


class RoleNotAllowed(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _require_owner(actor) -> None:
    if pws_rules.ROLE_PWS_OWNER not in actor.roles:
        raise RoleNotAllowed("PWS freeze requires BO-07 whitelist_owner role")


# ---------- Q28 pwsReadiness 5 项 ----------

async def evaluate_readiness(session, product_space_id: str) -> dict:
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)

    pool = (
        await session.scalars(
            select(FieldPool).where(FieldPool.product_space_id == product_space_id)
        )
    ).first()

    approved_atom_count = (
        await session.scalar(
            select(func.count())
            .select_from(ProductAtomInstance)
            .where(
                ProductAtomInstance.product_space_id == product_space_id,
                ProductAtomInstance.status == ATOM_APPROVED,
            )
        )
    ) or 0

    active_pwc_count = (
        await session.scalar(
            select(func.count())
            .select_from(ConditionPackage)
            .where(
                ConditionPackage.product_space_id == product_space_id,
                ConditionPackage.gate_status == pwc_rules.GATE_APPROVED,
                ConditionPackage.status.in_(_ACTIVE_PWC_STATUSES),
            )
        )
    ) or 0

    blocked_conflict_count = (
        await session.scalar(
            select(func.count())
            .select_from(AtomConflict)
            .join(AtomCandidate, AtomCandidate.candidate_id == AtomConflict.candidate_id)
            .where(
                AtomCandidate.product_space_id == product_space_id,
                AtomConflict.status == "blocked",
                AtomConflict.resolved_at.is_(None),
            )
        )
    ) or 0

    pending_pool_count = (
        await session.scalar(
            select(func.count())
            .select_from(FieldPool)
            .where(
                FieldPool.product_space_id == product_space_id,
                FieldPool.gate == "pending_gate",
            )
        )
    ) or 0

    checks = {
        "approved_field_pool": pool is not None and pool.gate == "approved",
        "enough_approved_atoms": approved_atom_count >= pws_rules.MIN_APPROVED_ATOMS,
        "active_pwc": active_pwc_count >= pws_rules.MIN_ACTIVE_PWCS,
        "no_unresolved_blocked_conflict": blocked_conflict_count == 0,
        "no_pending_gate_fields": pending_pool_count == 0,
    }
    return {
        "checks": checks,
        "all_green": pws_rules.all_green(checks),
        "counts": {
            "approved_atoms": approved_atom_count,
            "active_pwcs": active_pwc_count,
            "unresolved_blocked_conflicts": blocked_conflict_count,
            "pending_gate_pools": pending_pool_count,
        },
        "pool_id": pool.pool_id if pool is not None else None,
    }


async def evaluate(session, product_space_id: str, actor) -> dict:
    """Q28：系统提请——全绿则建/复用"可冻结"待办（7 天 due，到期 sweep 升级）。"""
    readiness = await evaluate_readiness(session, product_space_id)
    todo_id = None
    if readiness["all_green"]:
        existing = (
            await session.scalars(
                select(OpsTodo).where(
                    OpsTodo.tenant_id == (await session.get(ProductSpace, product_space_id)).tenant_id,
                    OpsTodo.todo_type == TODO_TYPE_PWS_READY,
                    OpsTodo.entity_type == ENTITY_PS,
                    OpsTodo.entity_id == product_space_id,
                    OpsTodo.status.in_(["open", "escalated"]),
                )
            )
        ).first()
        if existing is None:
            ps = await session.get(ProductSpace, product_space_id)
            todo = OpsTodo(
                tenant_id=ps.tenant_id,
                todo_type=TODO_TYPE_PWS_READY,
                entity_type=ENTITY_PS,
                entity_id=product_space_id,
                assignee_role=pws_rules.ROLE_PWS_OWNER,
                detail={"summary": readiness["counts"], "proposed_by": actor.id},
                due_at=_now() + timedelta(days=pws_rules.READY_TODO_DUE_DAYS),
            )
            session.add(todo)
            await session.flush()
            todo_id = todo.todo_id
            await append_audit(
                session,
                tenant_id=ps.tenant_id,
                actor_id=actor.id,
                actor_roles=actor.roles,
                action="pws.readiness_todo",
                entity_type=ENTITY_PS,
                entity_id=product_space_id,
                detail=readiness["counts"],
            )
        else:
            todo_id = existing.todo_id
    await session.commit()
    readiness["todo_id"] = todo_id
    return readiness


# ---------- Q31 冻结 / Q29 重冻 / Q30 换版 ----------

async def _snapshot_assets(session, product_space_id: str) -> dict:
    atoms = (
        await session.scalars(
            select(ProductAtomInstance)
            .where(
                ProductAtomInstance.product_space_id == product_space_id,
                ProductAtomInstance.status == ATOM_APPROVED,
            )
            .order_by(ProductAtomInstance.created_at, ProductAtomInstance.atom_id)
        )
    ).all()
    atom_ids = [a.atom_id for a in atoms]

    pwcs = (
        await session.scalars(
            select(ConditionPackage)
            .where(
                ConditionPackage.product_space_id == product_space_id,
                ConditionPackage.gate_status == pwc_rules.GATE_APPROVED,
                ConditionPackage.status.in_(_ACTIVE_PWC_STATUSES),
            )
            .order_by(ConditionPackage.created_at, ConditionPackage.pwc_id)
        )
    ).all()
    pwc_ids = [p.pwc_id for p in pwcs]
    items = (
        await session.scalars(
            select(PwcComboItem)
            .where(PwcComboItem.pwc_id.in_(pwc_ids or ["_"]))
            .order_by(PwcComboItem.item_id)
        )
    ).all()
    items_by_pwc: dict[str, list[PwcComboItem]] = {}
    for it in items:
        items_by_pwc.setdefault(it.pwc_id, []).append(it)
    return {
        "atoms": atoms,
        "atom_ids": atom_ids,
        "pwcs": pwcs,
        "pwc_ids": pwc_ids,
        "items_by_pwc": items_by_pwc,
    }


async def freeze(session, product_space_id: str, body, actor) -> dict:
    _require_owner(actor)
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)

    readiness = await evaluate_readiness(session, product_space_id)
    if not readiness["all_green"]:
        raise ReadinessNotGreen(readiness["checks"])

    active = (
        await session.scalars(
            select(PwsSnapshot).where(
                PwsSnapshot.product_space_id == product_space_id,
                PwsSnapshot.is_active.is_(True),
                PwsSnapshot.status == pws_rules.PWS_FROZEN,
            )
        )
    ).first()

    tier = None
    if active is not None:
        if body.reason_code is None:
            raise RefreezeReasonRequired("refreeze requires a Q29 reason_code")
        try:
            tier = pws_rules.refreeze_tier(body.reason_code)
        except ValueError as exc:
            raise RefreezeReasonInvalid(str(exc)) from exc
        if tier == pws_rules.REFREEZE_NONE:
            raise RefreezeNotNeeded("reason maps to Q29 'none': no new version")

    assets = await _snapshot_assets(session, product_space_id)
    versions = (
        await session.scalars(
            select(PwsSnapshot.version).where(
                PwsSnapshot.product_space_id == product_space_id
            )
        )
    ).all()
    version = pws_rules.next_version(list(versions))
    fingerprint = pws_rules.snapshot_fingerprint(assets["atom_ids"], assets["pwc_ids"])

    # Q33：同租户内指纹查重，仅提示、永不驳回（跨客户同款永不驳回）。
    others = (
        await session.scalars(
            select(PwsSnapshot).where(
                PwsSnapshot.tenant_id == ps.tenant_id,
                PwsSnapshot.status == pws_rules.PWS_FROZEN,
                PwsSnapshot.product_space_id != product_space_id,
            )
        )
    ).all()
    dup_hints = [
        {"pws_id": row.pws_id, "product_space_id": row.product_space_id, "version": row.version}
        for row in pws_rules.same_tenant_duplicates(
            fingerprint,
            [
                {
                    "fingerprint": row.fingerprint,
                    "pws_id": row.pws_id,
                    "product_space_id": row.product_space_id,
                    "version": row.version,
                }
                for row in others
            ],
        )
    ]

    snapshot_payload = {
        "pool_id": readiness["pool_id"],
        "atoms": [
            {
                "atom_id": a.atom_id,
                "dimension_id": a.dimension_id,
                "fid": a.fid,
                "content": a.content,
                "fact_type": a.fact_type,
                "status": a.status,
            }
            for a in assets["atoms"]
        ],
        "pwcs": [
            {
                "pwc_id": p.pwc_id,
                "goals": list(p.goals),
                "score": p.score,
                "combo": [
                    {"atom_id": it.atom_id, "dimension_id": it.dimension_id, "fid": it.fid}
                    for it in assets["items_by_pwc"].get(p.pwc_id, [])
                ],
            }
            for p in assets["pwcs"]
        ],
    }

    snapshot = PwsSnapshot(
        tenant_id=ps.tenant_id,
        product_space_id=product_space_id,
        version=version,
        status=pws_rules.PWS_FROZEN,
        is_active=True,
        pool_id=readiness["pool_id"],
        fingerprint=fingerprint,
        snapshot=snapshot_payload,
        readiness=readiness,
        refreeze_tier=tier,
        reason_code=body.reason_code,
        created_by=actor.id,
    )
    session.add(snapshot)
    await session.flush()

    seq = 0
    for atom in assets["atoms"]:
        seq += 1
        session.add(
            PwsSnapshotItem(
                pws_id=snapshot.pws_id,
                kind="atom",
                ref_id=atom.atom_id,
                dimension_id=atom.dimension_id,
                seq=seq,
                payload={"content": atom.content, "fid": atom.fid, "fact_type": atom.fact_type},
            )
        )
    for pwc in assets["pwcs"]:
        seq += 1
        session.add(
            PwsSnapshotItem(
                pws_id=snapshot.pws_id,
                kind="pwc",
                ref_id=pwc.pwc_id,
                seq=seq,
                payload={
                    "goals": list(pwc.goals),
                    "score": pwc.score,
                    "combo": [
                        {"atom_id": it.atom_id, "dimension_id": it.dimension_id}
                        for it in assets["items_by_pwc"].get(pwc.pwc_id, [])
                    ],
                },
            )
        )

    dispositions = None
    if active is not None:
        active.is_active = False
        active.status = pws_rules.PWS_SUPERSEDED
        active.superseded_by = snapshot.pws_id
        session.add(
            PwsFreezeLog(
                tenant_id=ps.tenant_id,
                product_space_id=product_space_id,
                pws_id=active.pws_id,
                event="supersede",
                tier=tier,
                reason_code=body.reason_code,
                detail={"new_version": version},
                actor_id=actor.id,
            )
        )
        session.add(
            PwsFreezeLog(
                tenant_id=ps.tenant_id,
                product_space_id=product_space_id,
                pws_id=snapshot.pws_id,
                event="refreeze",
                tier=tier,
                reason_code=body.reason_code,
                detail={"supersedes": active.version},
                actor_id=actor.id,
            )
        )
        # Q30 四行处置：①旧版只读已落库；②草稿作废/③未发布待复查/④已发布标记
        # 的对象（段11 FCW、段12 成品）尚未实现，计数占位随 M8/段12 接入。
        dispositions = {
            "superseded_version": active.version,
            "draft_fcws_voided": [],
            "unpublished_pending_recheck": tier == pws_rules.REFREEZE_FORCED,
            "published_marked_outdated": 0,
        }
    else:
        session.add(
            PwsFreezeLog(
                tenant_id=ps.tenant_id,
                product_space_id=product_space_id,
                pws_id=snapshot.pws_id,
                event="freeze",
                actor_id=actor.id,
            )
        )

    # Q28：冻结后关闭"可冻结"待办。
    open_todos = (
        await session.scalars(
            select(OpsTodo).where(
                OpsTodo.tenant_id == ps.tenant_id,
                OpsTodo.todo_type == TODO_TYPE_PWS_READY,
                OpsTodo.entity_type == ENTITY_PS,
                OpsTodo.entity_id == product_space_id,
                OpsTodo.status.in_(["open", "escalated"]),
            )
        )
    ).all()
    for todo in open_todos:
        todo.status = "resolved"
        todo.resolved_at = _now()
        todo.resolution = "frozen"

    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pws.freeze" if active is None else "pws.refreeze",
        entity_type="pws_snapshot",
        entity_id=snapshot.pws_id,
        detail={"version": version, "tier": tier, "reason_code": body.reason_code},
    )
    await session.commit()
    return {
        "snapshot": snapshot,
        "dup_hints": dup_hints,
        "dispositions": dispositions,
    }


# ---------- Q32 急停 ----------

async def revoke(session, pws_id: str, reason: str, actor) -> PwsSnapshot:
    _require_owner(actor)
    snapshot = await session.get(PwsSnapshot, pws_id)
    if snapshot is None:
        raise PwsNotFound(pws_id)
    if snapshot.status != pws_rules.PWS_FROZEN or not snapshot.is_active:
        raise WrongPwsState(f"PWS {pws_id} is {snapshot.status}, only active frozen can be revoked")

    snapshot.is_active = False
    snapshot.status = pws_rules.PWS_REVOKED
    snapshot.revoked_by = actor.id
    snapshot.revoked_at = _now()
    snapshot.revoke_reason = reason
    session.add(
        PwsFreezeLog(
            tenant_id=snapshot.tenant_id,
            product_space_id=snapshot.product_space_id,
            pws_id=snapshot.pws_id,
            event="revoke",
            detail={"reason": reason},
            actor_id=actor.id,
        )
    )
    await append_audit(
        session,
        tenant_id=snapshot.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pws.revoke",
        entity_type="pws_snapshot",
        entity_id=snapshot.pws_id,
        detail={"version": snapshot.version, "reason": reason},
    )
    await session.commit()
    return snapshot


# ---------- 查询 ----------

async def list_versions(session, product_space_id: str) -> list[PwsSnapshot]:
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)
    rows = list(
        (
            await session.scalars(
                select(PwsSnapshot)
                .where(PwsSnapshot.product_space_id == product_space_id)
                .order_by(PwsSnapshot.created_at.desc())
            )
        ).all()
    )
    # created_at 同秒时按主版本号兜底，保证 v2.0 排在 v1.0 前（SQLite 测试易撞秒）
    return sorted(rows, key=lambda s: (s.created_at, pws_rules.version_major(s.version)), reverse=True)


async def get_snapshot(session, pws_id: str) -> PwsSnapshot:
    snapshot = await session.get(PwsSnapshot, pws_id)
    if snapshot is None:
        raise PwsNotFound(pws_id)
    return snapshot


async def list_items(session, pws_ids: list[str]) -> dict[str, list[PwsSnapshotItem]]:
    if not pws_ids:
        return {}
    rows = (
        await session.scalars(
            select(PwsSnapshotItem)
            .where(PwsSnapshotItem.pws_id.in_(pws_ids))
            .order_by(PwsSnapshotItem.seq)
        )
    ).all()
    grouped: dict[str, list[PwsSnapshotItem]] = {pid: [] for pid in pws_ids}
    for row in rows:
        grouped.setdefault(row.pws_id, []).append(row)
    return grouped
