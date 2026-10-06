"""段7/8 静态底表 REST 端点（08 M11）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.model_registry import gateway
from app.core.rbac import OPERATIONS, PermissionDenied, require_any_role
from app.core.staff_auth.deps import require_internal_actor
from app.platform.platform_adaptation import service
from app.platform.platform_adaptation.schemas import (
    ActorOnly,
    AdapterCandidateCreate,
    CandidateApprove,
    CandidateReject,
    EventUpsert,
    FitWeightPut,
    PcpCreate,
    PcpUpdate,
    PlatformAdapterPreviewRequest,
    RecalcCandidateCreate,
    RuleCreate,
    SlotTypeDefaultPut,
    SlotUpsert,
)

router = APIRouter(tags=["platform-adaptation"])

# Q242：段7/8 底表写口只认已验真 staff 令牌；读口仍走 query actor 的
# require_operations_view（Q118 口径，门控关时不强求凭证）。
_ops_gate = require_internal_actor(OPERATIONS)


def require_operations_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    # Q109/Q118：矩阵把段7/8 静态底表管理面读口（fit-weights/publish-slots/
    # slot-type-defaults）与写口同组标 operations，读口同型补 query actor 闸。
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, OPERATIONS)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def _slot_view(s) -> dict:
    return {
        "slot_id": s.slot_id,
        "platform": s.platform,
        "code": s.code,
        "name": s.name,
        "slot_type": s.slot_type,
        "chars_max": s.chars_max,
        "dur_min": s.dur_min,
        "dur_max": s.dur_max,
        "traffic": s.traffic,
        "safe": s.safe,
        "conv": s.conv,
        "load": s.load,
        "score_source": s.score_source,
        "risk": s.risk,
        "gate": s.gate,
        "source_url": s.source_url,
        "status": s.status,
    }


def _rule_view(r) -> dict:
    return {
        "rule_id": r.rule_id,
        "selector_level": r.selector_level,
        "platform": r.platform,
        "slot_type": r.slot_type,
        "slot_id": r.slot_id,
        "country": r.country,
        "effect": r.effect,
        "note": r.note,
        "status": r.status,
    }


def _pcp_view(p) -> dict:
    return {
        "pcp_id": p.pcp_id,
        "tenant_id": p.tenant_id,
        "product_space_id": p.product_space_id,
        "platform": p.platform,
        "template_code": p.template_code,
        "weights": p.weights,
        "status": p.status,
    }


def _event_view(e) -> dict:
    return {
        "event_id": e.event_id,
        "platform": e.platform,
        "slot_id": e.slot_id,
        "event_type": e.event_type,
        "severity": e.severity,
        "effective_start": e.effective_start.isoformat(),
        "effective_end": e.effective_end.isoformat() if e.effective_end else None,
        "note": e.note,
        "status": e.status,
    }


def _candidate_view(c) -> dict:
    return {
        "candidate_id": c.candidate_id,
        "pcp_id": c.pcp_id,
        "tenant_id": c.tenant_id,
        "product_space_id": c.product_space_id,
        "platform": c.platform,
        "source": c.source,
        "proposed_weights": c.proposed_weights,
        "change_list": c.change_list,
        "status": c.status,
        "rejected_reason": c.rejected_reason,
        "created_by": c.created_by,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "approved_by": c.approved_by,
        "approved_at": c.approved_at.isoformat() if c.approved_at else None,
    }


# ---------- 发布位档案 ----------

@router.get("/api/admin/publish-slots")
async def list_slots(
    platform: str | None = None,
    status: str | None = "active",
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_operations_view),
) -> list[dict]:
    return [_slot_view(s) for s in await service.list_slots(session, platform=platform, status=status)]


@router.post("/api/admin/publish-slots", status_code=201)
async def create_slot(
    body: SlotUpsert,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        slot = await service.create_slot(session, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.SlotCodeTaken as exc:
        raise HTTPException(409, f"slot code taken: {exc}") from exc
    await session.commit()
    return _slot_view(slot)


@router.put("/api/admin/publish-slots/{slot_id}")
async def update_slot(
    slot_id: str,
    body: SlotUpsert,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        slot = await service.update_slot(session, slot_id, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.SlotNotFound as exc:
        raise HTTPException(404, f"slot not found: {exc}") from exc
    except service.SlotCodeTaken as exc:
        raise HTTPException(409, f"slot code taken: {exc}") from exc
    await session.commit()
    return _slot_view(slot)


@router.delete("/api/admin/publish-slots/{slot_id}", status_code=204)
async def archive_slot(
    slot_id: str,
    body: ActorOnly,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> None:
    try:
        await service.archive_slot(session, slot_id, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.SlotNotFound as exc:
        raise HTTPException(404, f"slot not found: {exc}") from exc
    await session.commit()


@router.get("/api/admin/publish-slots/{slot_id}/fit-score")
async def fit_score(
    slot_id: str, goal: str, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        return await service.fit_score(session, slot_id, goal)
    except service.SlotNotFound as exc:
        raise HTTPException(404, f"slot not found: {exc}") from exc


# ---------- Q34 目的权重矩阵 ----------

@router.get("/api/admin/fit-weights")
async def list_fit_weights(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_operations_view),
) -> list[dict]:
    return [
        {"goal": r.goal, "weights": r.weights, "updated_by": r.updated_by}
        for r in await service.list_fit_weights(session)
    ]


@router.put("/api/admin/fit-weights")
async def put_fit_weights(
    body: FitWeightPut,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        row = await service.put_fit_weights(session, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.GoalNotFound as exc:
        raise HTTPException(404, f"goal not found or archived: {exc}") from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    await session.commit()
    return {"goal": row.goal, "weights": row.weights}


# ---------- 平台规则 ----------

@router.get("/api/admin/platform-rules")
async def list_rules(
    platform: str | None = None,
    slot_type: str | None = None,
    status: str | None = "active",
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return [
        _rule_view(r)
        for r in await service.list_rules(session, platform=platform, slot_type=slot_type, status=status)
    ]


@router.post("/api/admin/platform-rules", status_code=201)
async def create_rule(
    body: RuleCreate,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        rule = await service.create_rule(session, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    except service.RuleConflict as exc:
        raise HTTPException(
            409,
            {
                "detail": "conflicting rules at same level/condition; resend with overwrite=true to replace",
                "conflicts": [_rule_view(r) for r in exc.conflicts],
            },
        ) from exc
    await session.commit()
    return _rule_view(rule)


@router.delete("/api/admin/platform-rules/{rule_id}", status_code=204)
async def archive_rule(
    rule_id: str,
    body: ActorOnly,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> None:
    try:
        await service.archive_rule(session, rule_id, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.RuleNotFound as exc:
        raise HTTPException(404, f"rule not found: {exc}") from exc
    await session.commit()


@router.get("/api/admin/platform-rules/match")
async def match_rules(
    platform: str,
    slot_type: str,
    slot_id: str | None = None,
    country: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await service.match_rules(
        session, platform=platform, slot_type=slot_type, slot_id=slot_id, country=country
    )
    # Q259：动态信号 advisory 回带——命中平台（及发布位）的当前生效事件，
    # 仅提示不改变规则裁决（Q37 事件→池字段映射【原文未给出，待补】）。
    events = await service.active_events_for(session, platform, slot_id=slot_id)
    result["events"] = [_event_view(e) for e in events]
    return result


@router.post("/api/admin/platform-adapter/preview")
async def platform_adapter_preview(
    body: PlatformAdapterPreviewRequest,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    """Q296 甲（design-v2-platform-adapter-business §3.1）：PLATFORM-ADAPTER 只读预览口。

    组三料（PWS 快照／Q36 规则命中／生效动态事件）→ 经模型网关调 PLATFORM-ADAPTER
    场景（V1 路由 synthetic）→ 四态建议直接回带。**零落库、零审计、不改任何判定、
    不产候选、不触 final_id**（PT 约束 4/6；Q249 FCW 预检只读口同型）。快照不存在
    404；无 frozen PWS 是协议内缺失形状（missing=true 五键、decision/gate 为 None
    不造假），不是错误。
    """
    try:
        return await service.platform_adapter_preview(
            session,
            pws_snapshot_id=body.pws_snapshot_id,
            platform=body.platform,
            slot_type=body.slot_type,
            slot_id=body.slot_id,
            country=body.country,
            previewed_by=verified.id,
        )
    except service.PwsSnapshotNotFound as exc:
        raise HTTPException(404, f"pws snapshot not found: {exc}") from exc
    except gateway.ModelConfigError as exc:
        raise HTTPException(422, str(exc)) from exc
    except gateway.ModelUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except gateway.GenerationUpstreamError as exc:
        raise HTTPException(502, str(exc)) from exc


# ---------- Q300 PLATFORM-ADAPTER 候选 + HumanGate（advisory）----------

def _adapter_candidate_view(c) -> dict:
    return {
        "candidate_id": c.candidate_id,
        "pws_snapshot_id": c.pws_snapshot_id,
        "platform": c.platform,
        "slot_type": c.slot_type,
        "slot_id": c.slot_id,
        "country": c.country,
        "source": c.source,
        "decision": c.decision,
        "reason": c.reason,
        "refs": c.refs,
        "missing": c.missing,
        "status": c.status,
        "rejected_reason": c.rejected_reason,
        "created_by": c.created_by,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "approved_by": c.approved_by,
        "approved_at": c.approved_at.isoformat() if c.approved_at else None,
    }


@router.get("/api/admin/platform-adapter/candidates")
async def list_adapter_candidates(
    status_filter: str | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_operations_view),
) -> list[dict]:
    rows = await service.list_adapter_candidates(session, status=status_filter)
    return [_adapter_candidate_view(c) for c in rows]


@router.post(
    "/api/admin/platform-adapter/candidates",
    status_code=201,
)
async def create_adapter_candidate(
    body: AdapterCandidateCreate,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        cand = await service.create_adapter_candidate(session, body, verified)
    except service.PwsSnapshotNotFound as exc:
        raise HTTPException(404, f"pws snapshot not found: {exc}") from exc
    except service.PendingCandidateExists as exc:
        raise HTTPException(409, f"pending candidate exists: {exc}") from exc
    except gateway.ModelConfigError as exc:
        raise HTTPException(422, str(exc)) from exc
    except gateway.ModelUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except gateway.GenerationUpstreamError as exc:
        raise HTTPException(502, str(exc)) from exc
    await session.commit()
    return _adapter_candidate_view(cand)


@router.post("/api/admin/platform-adapter/candidates/{candidate_id}/approve")
async def approve_adapter_candidate(
    candidate_id: str,
    body: CandidateApprove,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        cand = await service.approve_adapter_candidate(session, candidate_id, verified)
    except service.AdapterCandidateNotFound as exc:
        raise HTTPException(404, f"candidate not found or not pending: {exc}") from exc
    await session.commit()
    return _adapter_candidate_view(cand)


@router.post("/api/admin/platform-adapter/candidates/{candidate_id}/reject")
async def reject_adapter_candidate(
    candidate_id: str,
    body: CandidateReject,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        cand = await service.reject_adapter_candidate(
            session, candidate_id, body.reason, verified
        )
    except service.AdapterCandidateNotFound as exc:
        raise HTTPException(404, f"candidate not found or not pending: {exc}") from exc
    except service.AdapterDecisionRequired as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.commit()
    return _adapter_candidate_view(cand)


# ---------- Q37 动态信号事件 ----------

@router.get("/api/admin/platform-dynamic-events")
async def list_events(
    platform: str | None = None,
    status: str | None = "active",
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_operations_view),
) -> list[dict]:
    return [_event_view(e) for e in await service.list_events(session, platform=platform, status=status)]


@router.post("/api/admin/platform-dynamic-events", status_code=201)
async def create_event(
    body: EventUpsert,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        ev = await service.create_event(session, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.EventPeriodInvalid as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.commit()
    return _event_view(ev)


@router.put("/api/admin/platform-dynamic-events/{event_id}")
async def update_event(
    event_id: str,
    body: EventUpsert,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        ev = await service.update_event(session, event_id, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.EventNotFound as exc:
        raise HTTPException(404, f"event not found: {exc}") from exc
    except service.EventPeriodInvalid as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.commit()
    return _event_view(ev)


@router.delete("/api/admin/platform-dynamic-events/{event_id}", status_code=204)
async def archive_event(
    event_id: str,
    body: ActorOnly,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> None:
    try:
        await service.archive_event(session, event_id, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.EventNotFound as exc:
        raise HTTPException(404, f"event not found: {exc}") from exc
    await session.commit()


# ---------- Q41/Q42 PCP 重算候选 HumanGate ----------

@router.get("/api/admin/pcp-recalc/candidates")
async def list_candidates(
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_operations_view),
) -> list[dict]:
    return [_candidate_view(c) for c in await service.list_candidates(session, status=status)]


@router.post("/api/admin/pcp-recalc/candidates", status_code=201)
async def create_candidate(
    body: RecalcCandidateCreate,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        cand = await service.create_candidate(session, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.PcpNotFound as exc:
        raise HTTPException(404, f"pcp not found or not active: {exc}") from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    except service.RecalcStepExceeded as exc:
        raise HTTPException(422, f"recalc step exceeded: {exc}") from exc
    except service.PendingCandidateExists as exc:
        raise HTTPException(409, f"pending candidate exists: {exc}") from exc
    await session.commit()
    return _candidate_view(cand)


@router.post("/api/admin/pcp-recalc/candidates/{candidate_id}/approve")
async def approve_candidate(
    candidate_id: str,
    body: CandidateApprove,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        cand = await service.approve_candidate(session, candidate_id, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.EventNotFound as exc:
        raise HTTPException(404, f"candidate not found or not pending: {exc}") from exc
    except service.PcpNotFound as exc:
        raise HTTPException(404, f"pcp not found or not active: {exc}") from exc
    await session.commit()
    return _candidate_view(cand)


@router.post("/api/admin/pcp-recalc/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: str,
    body: CandidateReject,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        cand = await service.reject_candidate(session, candidate_id, body.reason, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.EventNotFound as exc:
        raise HTTPException(404, f"candidate not found or not pending: {exc}") from exc
    await session.commit()
    return _candidate_view(cand)


# ---------- slotType 默认值 ----------

@router.get("/api/admin/slot-type-defaults")
async def list_slot_type_defaults(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_operations_view),
) -> list[dict]:
    return [
        {
            "slot_type": r.slot_type,
            "daily_limit_min": r.daily_limit_min,
            "daily_limit_max": r.daily_limit_max,
            "defaults": r.defaults,
        }
        for r in await service.list_slot_type_defaults(session)
    ]


@router.put("/api/admin/slot-type-defaults")
async def put_slot_type_default(
    body: SlotTypeDefaultPut,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        row = await service.put_slot_type_default(session, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    await session.commit()
    return {
        "slot_type": row.slot_type,
        "daily_limit_min": row.daily_limit_min,
        "daily_limit_max": row.daily_limit_max,
        "defaults": row.defaults,
    }


# ---------- 段8 PCP 权重 ----------

@router.get("/api/admin/pcp-templates")
async def list_templates(session: AsyncSession = Depends(get_session)) -> list[dict]:
    return [
        {"template_id": t.template_id, "code": t.code, "name": t.name, "weights": t.weights}
        for t in await service.list_templates(session)
    ]


@router.get("/api/product-spaces/{product_space_id}/pcp")
async def list_pcps(
    product_space_id: str, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    return [_pcp_view(p) for p in await service.list_pcps(session, product_space_id)]


@router.post("/api/product-spaces/{product_space_id}/pcp", status_code=201)
async def create_pcp(
    product_space_id: str,
    body: PcpCreate,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        pcp = await service.create_pcp(session, product_space_id, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.PcpNotFound as exc:
        raise HTTPException(404, f"product space not found: {exc}") from exc
    except service.TemplateNotFound as exc:
        raise HTTPException(404, f"pcp template not found: {exc}") from exc
    except service.PcpExists as exc:
        raise HTTPException(409, f"active pcp exists: {exc}") from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    await session.commit()
    return _pcp_view(pcp)


@router.put("/api/pcp/{pcp_id}")
async def update_pcp(
    pcp_id: str,
    body: PcpUpdate,
    session: AsyncSession = Depends(get_session),
    verified: Actor = Depends(_ops_gate),
) -> dict:
    try:
        pcp = await service.update_pcp(session, pcp_id, body, verified)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.PcpNotFound as exc:
        raise HTTPException(404, f"pcp not found: {exc}") from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    await session.commit()
    return _pcp_view(pcp)
