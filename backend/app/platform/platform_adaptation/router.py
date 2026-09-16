"""段7/8 静态底表 REST 端点（08 M11）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.rbac import OPERATIONS, PermissionDenied, require_any_role
from app.platform.platform_adaptation import service
from app.platform.platform_adaptation.schemas import (
    ActorOnly,
    FitWeightPut,
    PcpCreate,
    PcpUpdate,
    RuleCreate,
    SlotTypeDefaultPut,
    SlotUpsert,
)

router = APIRouter(tags=["platform-adaptation"])


def require_fit_weights_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
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


# ---------- 发布位档案 ----------

@router.get("/api/admin/publish-slots")
async def list_slots(
    platform: str | None = None,
    status: str | None = "active",
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return [_slot_view(s) for s in await service.list_slots(session, platform=platform, status=status)]


@router.post("/api/admin/publish-slots", status_code=201)
async def create_slot(body: SlotUpsert, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        slot = await service.create_slot(session, body, body.actor)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.SlotCodeTaken as exc:
        raise HTTPException(409, f"slot code taken: {exc}") from exc
    await session.commit()
    return _slot_view(slot)


@router.put("/api/admin/publish-slots/{slot_id}")
async def update_slot(
    slot_id: str, body: SlotUpsert, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        slot = await service.update_slot(session, slot_id, body, body.actor)
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
    slot_id: str, body: ActorOnly, session: AsyncSession = Depends(get_session)
) -> None:
    try:
        await service.archive_slot(session, slot_id, body.actor)
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
    _: Actor = Depends(require_fit_weights_view),
) -> list[dict]:
    return [
        {"goal": r.goal, "weights": r.weights, "updated_by": r.updated_by}
        for r in await service.list_fit_weights(session)
    ]


@router.put("/api/admin/fit-weights")
async def put_fit_weights(body: FitWeightPut, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        row = await service.put_fit_weights(session, body, body.actor)
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
async def create_rule(body: RuleCreate, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        rule = await service.create_rule(session, body, body.actor)
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
    rule_id: str, body: ActorOnly, session: AsyncSession = Depends(get_session)
) -> None:
    try:
        await service.archive_rule(session, rule_id, body.actor)
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
    return await service.match_rules(
        session, platform=platform, slot_type=slot_type, slot_id=slot_id, country=country
    )


# ---------- slotType 默认值 ----------

@router.get("/api/admin/slot-type-defaults")
async def list_slot_type_defaults(session: AsyncSession = Depends(get_session)) -> list[dict]:
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
    body: SlotTypeDefaultPut, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        row = await service.put_slot_type_default(session, body, body.actor)
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
    product_space_id: str, body: PcpCreate, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        pcp = await service.create_pcp(session, product_space_id, body, body.actor)
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
    pcp_id: str, body: PcpUpdate, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        pcp = await service.update_pcp(session, pcp_id, body, body.actor)
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.PcpNotFound as exc:
        raise HTTPException(404, f"pcp not found: {exc}") from exc
    except service.ValidationFailed as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc
    await session.commit()
    return _pcp_view(pcp)
