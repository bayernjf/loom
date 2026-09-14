"""段11 FCW 组装服务（PT-FCW-ASM-V1.0，Q52-Q55）。

V1 纯机械：不做 AI 选料（WF-09 Skill 随 V2），六路材料按键解析、
过 7 项 Guard、全绿才在本模块（E1.1 publishFCW，全系统唯一出口）
生成 final_id；每次尝试（发/未发）均 writeAudit（Q55）。
"""

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.audit import append_audit
from app.decision.compliance_center.service import gate_view
from app.decision.layer_strategy.models import (
    KIND_CEP,
    KIND_CSP,
    KIND_CSTP,
    Package,
)
from app.final.final_whitelist import fcw_rules
from app.final.final_whitelist.models import (
    PUBLISH_PUBLISHED,
    FcwAssemblyTask,
    FinalContentWhitelist,
)
from app.platform.platform_adaptation.models import (
    GoalFitWeight,
    PcpWeightTable,
    PublishSlot,
)
from app.platform.platform_adaptation.pa_rules import compute_fit_score
from app.product.condition.models import ContentGoal
from app.product.whitelist_center.models import (
    PwsSnapshot,
    PwsSnapshotItem,
)

ROLE_OPERATIONS = "operations"
TASK_STATUS_COMPLETED = "completed"


class RoleNotAllowed(Exception):
    pass


class ProductSpaceNotFound(Exception):
    pass


class PwsNotFound(Exception):
    pass


class SlotNotFound(Exception):
    pass


class GoalInvalid(Exception):
    pass


class MaterialMissing(Exception):
    """六路材料不齐（无 active PCP/三包/匹配目的的骨架 PWC）。"""


class GuardsFailed(Exception):
    def __init__(self, guard_results: list[dict]):
        self.guard_results = guard_results
        super().__init__("FCW guards failed")


class DuplicateIssuance(Exception):
    pass


class InvalidRequest(Exception):
    pass


def _require_ops(actor) -> None:
    if ROLE_OPERATIONS not in actor.roles:
        raise RoleNotAllowed("requires operations role")


async def _resolve_pws(session, product_space_id: str, pws_id: str | None):
    if pws_id is not None:
        pws = await session.get(PwsSnapshot, pws_id)
        if pws is None or pws.product_space_id != product_space_id:
            raise PwsNotFound(pws_id or "")
        return pws
    pws = (
        await session.scalars(
            select(PwsSnapshot).where(
                PwsSnapshot.product_space_id == product_space_id,
                PwsSnapshot.is_active.is_(True),
            )
        )
    ).first()
    if pws is None:
        raise PwsNotFound(f"active pws for {product_space_id}")
    return pws


async def _validate_goal(session, goal: str) -> None:
    row = await session.get(ContentGoal, goal)
    if row is None or row.status != "active":
        raise GoalInvalid(goal)


async def _resolve_slot(session, slot_id: str, platform: str) -> PublishSlot:
    slot = await session.get(PublishSlot, slot_id)
    if slot is None or slot.status != "active":
        raise SlotNotFound(slot_id)
    if slot.platform != platform:
        raise InvalidRequest(
            f"slot {slot_id} platform {slot.platform} != {platform}"
        )
    return slot


async def _resolve_packages(session, ps_id: str, tenant: str, platform: str, goal: str):
    by_kind: dict[str, Package] = {}
    rows = (
        await session.scalars(
            select(Package).where(
                Package.product_space_id == ps_id,
                Package.tenant_id == tenant,
                Package.platform == platform,
                Package.goal == goal,
                Package.status == "active",
            )
        )
    ).all()
    for row in rows:
        by_kind.setdefault(row.kind, row)
    missing = [k for k in (KIND_CSP, KIND_CSTP, KIND_CEP) if k not in by_kind]
    if missing:
        raise MaterialMissing(f"active packages missing: {','.join(missing)}")
    return by_kind[KIND_CSP], by_kind[KIND_CSTP], by_kind[KIND_CEP]


async def _resolve_pcp(session, ps_id: str, tenant: str, platform: str) -> PcpWeightTable:
    pcp = (
        await session.scalars(
            select(PcpWeightTable).where(
                PcpWeightTable.product_space_id == ps_id,
                PcpWeightTable.tenant_id == tenant,
                PcpWeightTable.platform == platform,
                PcpWeightTable.status == "active",
            )
        )
    ).first()
    if pcp is None:
        raise MaterialMissing(f"active PCP for {ps_id}/{platform}")
    return pcp


async def _resolve_skeleton_pwc(session, pws_id: str, goal: str):
    """从冻结快照物化行选骨架 PWC：目的有交集取评分最高（null 末位）。"""
    items = (
        await session.scalars(
            select(PwsSnapshotItem).where(
                PwsSnapshotItem.pws_id == pws_id,
                PwsSnapshotItem.kind == "pwc",
            )
        )
    ).all()
    candidates = [
        it for it in items if goal in (it.payload.get("goals") or [])
    ]
    if not candidates:
        raise MaterialMissing(f"frozen PWC serving goal {goal}")
    candidates.sort(key=lambda it: (it.payload.get("score") is None, it.payload.get("score") or 0))
    return candidates[-1]


def _ref(row) -> fcw_rules.MaterialRef:
    return fcw_rules.MaterialRef(
        ref_id=row.package_id if hasattr(row, "package_id") else row.pcp_id,
        product_space_id=row.product_space_id,
        tenant_id=row.tenant_id,
        status=row.status,
        gate=getattr(row, "gate", fcw_rules.GATE_APPROVED),
    )


def _gate_ref(view: dict) -> fcw_rules.Gate:
    return fcw_rules.Gate(
        latest_report_id=view["latest_report_id"],
        report_status=view["report_status"],
        block_required=view["block_required"],
        cleaning_passed=view["cleaning_passed"],
        law_review_required=view["law_review_required"],
        law_review_status=view["law_review_status"],
        law_review_passed=view["law_review_passed"],
    )


def _guard_payload(results) -> list[dict]:
    return [
        {"code": r.code, "passed": r.passed, "detail": r.detail} for r in results
    ]


async def assemble_one(
    session,
    *,
    product_space_id: str,
    platform: str,
    goal: str,
    slot_id: str,
    actor,
    country: str | None = None,
    pws_id: str | None = None,
    task_id: str | None = None,
) -> FinalContentWhitelist:
    """单条机械组装。材料齐 + 7 项全绿才 mint final_id，否则抛 GuardsFailed。"""
    _require_ops(actor)
    await _validate_goal(session, goal)
    pws = await _resolve_pws(session, product_space_id, pws_id)
    slot = await _resolve_slot(session, slot_id, platform)
    pcp = await _resolve_pcp(session, product_space_id, pws.tenant_id, platform)
    csp, cstp, cep = await _resolve_packages(
        session, product_space_id, pws.tenant_id, platform, goal
    )
    pwc_item = await _resolve_skeleton_pwc(session, pws.pws_id, goal)

    view = await gate_view(session, pws.pws_id, country)
    materials = fcw_rules.Materials(
        pws_id=pws.pws_id,
        pws_status=pws.status,
        pws_is_active=pws.is_active,
        pws_product_space_id=pws.product_space_id,
        pws_tenant_id=pws.tenant_id,
        gate=_gate_ref(view),
        pcp=_ref(pcp),
        csp=_ref(csp),
        cstp=_ref(cstp),
        cep=_ref(cep),
        request_product_space_id=product_space_id,
    )
    results = fcw_rules.evaluate_guards(materials)
    guard_payload = _guard_payload(results)
    if not fcw_rules.guards_passed(results):
        await append_audit(
            session,
            tenant_id=pws.tenant_id,
            actor_id=actor.id,
            actor_roles=actor.roles,
            action="fcw.assembly_blocked",
            entity_type="fcw_assembly",
            entity_id=f"{pws.pws_id}:{slot_id}",
            detail={
                "task_id": task_id,
                "platform": platform,
                "goal": goal,
                "country": country,
                "pwc_id": pwc_item.ref_id,
                "guards": guard_payload,
            },
        )
        raise GuardsFailed(guard_payload)

    dup = (
        await session.scalars(
            select(FinalContentWhitelist).where(
                FinalContentWhitelist.pws_id == pws.pws_id,
                FinalContentWhitelist.pwc_id == pwc_item.ref_id,
                FinalContentWhitelist.platform == platform,
                FinalContentWhitelist.slot_id == slot_id,
                FinalContentWhitelist.country == country,
            )
        )
    ).first()
    if dup is not None:
        raise DuplicateIssuance(dup.final_id)

    fit_row = await session.get(GoalFitWeight, goal)
    slot_fit = (
        compute_fit_score(slot, fit_row.weights) if fit_row is not None else None
    )
    score_outcome = fcw_rules.score_fcw(
        pwc_score=pwc_item.payload.get("score"),
        slot_fit_score=slot_fit,
        package_confs=[csp.conf, cstp.conf, cep.conf],
    )

    fcw = FinalContentWhitelist(
        task_id=task_id,
        tenant_id=pws.tenant_id,
        product_space_id=product_space_id,
        pws_id=pws.pws_id,
        pwc_id=pwc_item.ref_id,
        pcp_id=pcp.pcp_id,
        csp_package_id=csp.package_id,
        cstp_package_id=cstp.package_id,
        cep_package_id=cep.package_id,
        ccr_report_id=view["latest_report_id"],
        platform=platform,
        slot_id=slot_id,
        goal=goal,
        country=country,
        score=score_outcome.score,
        score_detail=score_outcome.detail,
        score_incomplete=score_outcome.incomplete,
        guards={"guards": guard_payload},
        guards_passed=True,
        publish_status=PUBLISH_PUBLISHED,
        issued_by=actor.id,
        published_at=datetime.now(tz=UTC),
    )
    session.add(fcw)
    await session.flush()
    await append_audit(
        session,
        tenant_id=pws.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="fcw.issued",
        entity_type="final_content_whitelist",
        entity_id=fcw.final_id,
        detail={
            "task_id": task_id,
            "E1_owner": "publishFCW",
            "materials": {
                "pws_id": pws.pws_id,
                "pwc_id": pwc_item.ref_id,
                "pcp_id": pcp.pcp_id,
                "csp_package_id": csp.package_id,
                "cstp_package_id": cstp.package_id,
                "cep_package_id": cep.package_id,
                "ccr_report_id": view["latest_report_id"],
                "platform": platform,
                "slot_id": slot_id,
                "goal": goal,
                "country": country,
            },
            "score": score_outcome.score,
            "guards": guard_payload,
        },
    )
    return fcw


async def create_task(session, body) -> FcwAssemblyTask:
    """Q55 任务驱动：同步逐条组装；单项失败不阻断其余，结果全留痕。"""
    _require_ops(body.actor)
    await _validate_goal(session, body.goal)
    # 早验参数：PS/active PWS/goal 不合法直接 4xx，不建空任务。
    pws = await _resolve_pws(session, body.product_space_id, body.pws_id)

    if body.slot_ids:
        if len(body.slot_ids) != body.count:
            raise InvalidRequest("slot_ids length must equal count")
        slot_ids = list(dict.fromkeys(body.slot_ids))
        if len(slot_ids) != len(body.slot_ids):
            raise InvalidRequest("duplicate slot_ids")
        for sid in slot_ids:
            await _resolve_slot(session, sid, body.platform)
    else:
        rows = (
            await session.scalars(
                select(PublishSlot).where(
                    PublishSlot.platform == body.platform,
                    PublishSlot.status == "active",
                )
            )
        ).all()
        slot_ids = [s.slot_id for s in rows[: body.count]]

    task = FcwAssemblyTask(
        tenant_id=pws.tenant_id,
        product_space_id=body.product_space_id,
        pws_id=pws.pws_id,
        platform=body.platform,
        goal=body.goal,
        country=body.country,
        requested_count=body.count,
        slot_ids=slot_ids,
        status="running",
        results={},
        created_by=body.actor.id,
    )
    session.add(task)
    await session.flush()

    issued: list[dict] = []
    failures: list[dict] = []
    for sid in slot_ids:
        try:
            fcw = await assemble_one(
                session,
                product_space_id=body.product_space_id,
                platform=body.platform,
                goal=body.goal,
                slot_id=sid,
                actor=body.actor,
                country=body.country,
                pws_id=pws.pws_id,
                task_id=task.task_id,
            )
            issued.append({"slot_id": sid, "final_id": fcw.final_id})
        except (MaterialMissing, GuardsFailed, DuplicateIssuance) as exc:
            payload = (
                exc.guard_results
                if isinstance(exc, GuardsFailed)
                else {"reason": str(exc)}
            )
            failures.append({"slot_id": sid, "detail": payload})

    task.results = {
        "requested": body.count,
        "resolved_slots": len(slot_ids),
        "issued": issued,
        "failures": failures,
    }
    task.status = TASK_STATUS_COMPLETED
    task.completed_at = datetime.now(tz=UTC)
    await append_audit(
        session,
        tenant_id=pws.tenant_id,
        actor_id=body.actor.id,
        actor_roles=body.actor.roles,
        action="fcw.assembly_task",
        entity_type="fcw_assembly_task",
        entity_id=task.task_id,
        detail={
            "requested": body.count,
            "issued_count": len(issued),
            "failure_count": len(failures),
        },
    )
    return task


async def list_fcw(session, product_space_id: str) -> list[FinalContentWhitelist]:
    return list(
        (
            await session.scalars(
                select(FinalContentWhitelist)
                .where(
                    FinalContentWhitelist.product_space_id == product_space_id
                )
                .order_by(FinalContentWhitelist.created_at.desc())
            )
        ).all()
    )


async def get_fcw(session, final_id: str) -> FinalContentWhitelist | None:
    return await session.get(FinalContentWhitelist, final_id)


async def get_task(session, task_id: str) -> FcwAssemblyTask | None:
    return await session.get(FcwAssemblyTask, task_id)


def fcw_view(fcw: FinalContentWhitelist) -> dict:
    return {
        "final_id": fcw.final_id,
        "task_id": fcw.task_id,
        "tenant_id": fcw.tenant_id,
        "product_space_id": fcw.product_space_id,
        "pws_id": fcw.pws_id,
        "pwc_id": fcw.pwc_id,
        "pcp_id": fcw.pcp_id,
        "csp_package_id": fcw.csp_package_id,
        "cstp_package_id": fcw.cstp_package_id,
        "cep_package_id": fcw.cep_package_id,
        "ccr_report_id": fcw.ccr_report_id,
        "platform": fcw.platform,
        "slot_id": fcw.slot_id,
        "goal": fcw.goal,
        "country": fcw.country,
        "score": fcw.score,
        "score_detail": fcw.score_detail,
        "score_incomplete": fcw.score_incomplete,
        "guards_passed": fcw.guards_passed,
        "guards": fcw.guards,
        "publish_status": fcw.publish_status,
        "issued_by": fcw.issued_by,
        "created_at": fcw.created_at,
        "published_at": fcw.published_at,
    }


def task_view(task: FcwAssemblyTask) -> dict:
    return {
        "task_id": task.task_id,
        "tenant_id": task.tenant_id,
        "product_space_id": task.product_space_id,
        "pws_id": task.pws_id,
        "platform": task.platform,
        "goal": task.goal,
        "country": task.country,
        "requested_count": task.requested_count,
        "slot_ids": task.slot_ids,
        "status": task.status,
        "results": task.results,
        "created_by": task.created_by,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
    }
