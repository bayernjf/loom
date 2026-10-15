"""段6 PWS 冻结服务：就绪门（line 2634）、Q28 待办、Q29/Q30/Q31/Q32 版本动作、Q33 同租户查重提示。

AI 不参与冻结：系统只做机械核验与待办提请，盖章动作的角色已按 Q329（Q242 乙案）由
BO-07（whitelist_owner，红线 line 7674）改判为 operations——whitelist_owner 不可签发
staff 令牌（Q178 限五内部角色），V1 代运营期冻结/吊销由运营执行，与 FCW final_id revoke
（Q250，OPERATIONS）同口径；whitelist_owner 保留为 Q28 原文角色，随 V2 客户侧认证回评。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.audit import append_audit
from app.core.rbac import OPERATIONS
from app.product.atom.atom_rules import ATOM_APPROVED
from app.product.atom.models import AtomCandidate, AtomConflict, ProductAtomInstance
from app.product.condition import pwc_rules
from app.product.condition.models import ConditionPackage, PwcComboItem
from app.product.fieldpool.models import FieldPool, FPDimension
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


def _require_ops(actor) -> None:
    # Q329（Q242 乙案）：BO-07 whitelist_owner 不可签发 staff 令牌，改判 operations。
    # service 层自判保留作非 HTTP 调用方（worker）兜底；HTTP 闸在 router（require_internal_actor）。
    if OPERATIONS not in actor.roles:
        raise RoleNotAllowed("PWS freeze/revoke requires operations role (Q329: BO-07 reassigned from whitelist_owner)")


# Q30 ②③④（Q350 清单二 #15 甲）：换版时对旧版关联 FCW 的真实处置。
TODO_TYPE_Q30_RECHECK = "q30_pws_recheck"
TODO_TYPE_Q30_OUTDATED = "q30_fcw_outdated_notify"


async def _apply_q30_dispositions(
    session,
    *,
    ps: ProductSpace,
    old_pws: PwsSnapshot,
    new_pws: PwsSnapshot,
    tier: str | None,
    reason_code: str | None,
    actor,
) -> dict:
    """Q30 四行处置的 ②③④（①＝旧版 superseded 只读，已由调用方落库）。

    ② draft FCW：复用 FCW 版本机 revoke 作废其 active 快照，并按同 platform/goal/
       country/slot 建 queued 重组装任务（指向新版 pws_id），由 worker 重发；
    ③ 未发布成品（publish_status != published 的非 draft 行）：forced（合规类
       原因）时建合规待复查待办，suggested 不强制（Q30 ③ 只对合规原因强制重生成）；
    ④ 已发布成品：FCW 行受 exit_guard 不可变，不回改、不追溯，仅计数＋建合规提醒
       待办（Q30 ④ 合规类原因「提醒到人」），通知客户自查。
    """
    # 惰性 import：final 包反向引用 product 包模型，避开模块加载环。
    from app.final.final_whitelist.models import (
        PUBLISH_DRAFT,
        PUBLISH_PUBLISHED,
        FcwAssemblyTask,
        FinalContentWhitelist,
    )
    from app.final.final_whitelist.service import revoke_fcw

    forced = tier == pws_rules.REFREEZE_FORCED
    old_fcws = (
        await session.scalars(
            select(FinalContentWhitelist).where(
                FinalContentWhitelist.pws_id == old_pws.pws_id
            )
        )
    ).all()

    draft_voided: list[str] = []
    unpublished_pending = False
    published_outdated = 0
    now = _now()

    for fcw in old_fcws:
        if fcw.publish_status == PUBLISH_DRAFT:
            # ② 作废草稿（其 active frozen 快照 → revoked），再排队按新版重组装。
            await revoke_fcw(
                session,
                fcw.final_id,
                f"Q30 ② old PWS {old_pws.version} superseded by {new_pws.version}",
                actor,
            )
            session.add(
                FcwAssemblyTask(
                    tenant_id=ps.tenant_id,
                    product_space_id=ps.product_space_id,
                    pws_id=new_pws.pws_id,
                    platform=fcw.platform,
                    goal=fcw.goal,
                    country=fcw.country,
                    requested_count=1,
                    slot_ids=[fcw.slot_id],
                    status="queued",
                    results={"reissues": {"voided_final_id": fcw.final_id}},
                    created_by=actor.id,
                )
            )
            draft_voided.append(fcw.final_id)
        elif fcw.publish_status == PUBLISH_PUBLISHED:
            # ④ 不追溯：仅计数；合规类原因建提醒待办到人。
            published_outdated += 1
            if forced:
                session.add(
                    OpsTodo(
                        tenant_id=ps.tenant_id,
                        todo_type=TODO_TYPE_Q30_OUTDATED,
                        entity_type="final_content_whitelist",
                        entity_id=fcw.final_id,
                        assignee_role=OPERATIONS,
                        detail={
                            "reason_code": reason_code,
                            "old_pws_id": old_pws.pws_id,
                            "new_pws_id": new_pws.pws_id,
                            "action": "notify_customer_self_check",
                        },
                        due_at=now + timedelta(days=pws_rules.ready_todo_due_days()),
                    )
                )
        else:
            # ③ 已生成未发布（非 draft 的中间态）：合规原因强制进待复查。
            if forced:
                unpublished_pending = True
                session.add(
                    OpsTodo(
                        tenant_id=ps.tenant_id,
                        todo_type=TODO_TYPE_Q30_RECHECK,
                        entity_type="final_content_whitelist",
                        entity_id=fcw.final_id,
                        assignee_role="internal_compliance",
                        detail={
                            "reason_code": reason_code,
                            "old_pws_id": old_pws.pws_id,
                            "new_pws_id": new_pws.pws_id,
                        },
                        due_at=now + timedelta(days=pws_rules.ready_todo_due_days()),
                    )
                )

    # ③ 保留原占位契约：forced（合规原因）恒为真——即使旧版下尚无 FCW 实体，
    # 也表达「该产品材料有待复查义务」（test_pws_api 依赖此布尔位）；
    # 有未发布实体时上面已按实体建待办，此处只是同一义务的聚合格口。
    unpublished_pending = forced

    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pws.q30_dispositions",
        entity_type="pws_snapshot",
        entity_id=new_pws.pws_id,
        detail={
            "old_version": old_pws.version,
            "draft_voided": draft_voided,
            "unpublished_pending_recheck": unpublished_pending,
            "published_outdated": published_outdated,
            "tier": tier,
        },
    )
    return {
        "superseded_version": old_pws.version,
        "draft_fcws_voided": draft_voided,
        "unpublished_pending_recheck": unpublished_pending,
        "published_marked_outdated": published_outdated,
    }


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

    # ⑤ pending_gate 字段=0（PRD line 2634 原文；docs/25 §8.1 #5 语义修正，Q361）：
    # 数的是**池内挂起的新字段候选**——FPDimension 引用未转正候选（candidate_id
    # 非空且 fid 未回填，Q13 转正 Gate 前）的维度行数，而不是旧口径
    # 「gate=pending_gate 的 FieldPool 池子数」（池子非 approved 已由 ① 拦下，
    # 旧口径让「池内挂起字段」漏检）。转正后 promote_candidate 回填 fid ⇒ 计数归零。
    pending_field_count = (
        await session.scalar(
            select(func.count())
            .select_from(FPDimension)
            .join(FieldPool, FPDimension.pool_id == FieldPool.pool_id)
            .where(
                FieldPool.product_space_id == product_space_id,
                FPDimension.candidate_id.is_not(None),
                FPDimension.fid.is_(None),
            )
        )
    ) or 0

    checks = {
        "approved_field_pool": pool is not None and pool.gate == "approved",
        "enough_approved_atoms": approved_atom_count >= pws_rules.min_approved_atoms(),
        "active_pwc": active_pwc_count >= pws_rules.min_active_pwcs(),
        "no_unresolved_blocked_conflict": blocked_conflict_count == 0,
        "no_pending_gate_fields": pending_field_count == 0,
    }
    return {
        "checks": checks,
        "all_green": pws_rules.all_green(checks),
        "counts": {
            "approved_atoms": approved_atom_count,
            "active_pwcs": active_pwc_count,
            "unresolved_blocked_conflicts": blocked_conflict_count,
            "pending_gate_fields": pending_field_count,
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
                assignee_role=OPERATIONS,
                detail={"summary": readiness["counts"], "proposed_by": actor.id},
                due_at=_now() + timedelta(days=pws_rules.ready_todo_due_days()),
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
    _require_ops(actor)
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
        # Q30 四行处置（Q350 清单二 #15 甲：②③④ 回填，①＝上方 superseded 只读）：
        # ② 旧版 draft FCW 作废快照并按新版排队重组装；
        # ③ forced（合规类原因）旧版材料进合规待复查待办；
        # ④ 旧版已发布成品不追溯（exit_guard 禁改 FCW 行），仅计数＋合规提醒到人。
        dispositions = await _apply_q30_dispositions(
            session,
            ps=ps,
            old_pws=active,
            new_pws=snapshot,
            tier=tier,
            reason_code=body.reason_code,
            actor=actor,
        )
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
    _require_ops(actor)
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
