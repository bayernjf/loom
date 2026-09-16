from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.rbac import (
    DICTIONARY_ADMIN,
    OPERATIONS,
    PermissionDenied,
    require_any_role,
)
from app.product.modeling import c7, service
from app.product.modeling.c1 import WeightSumError
from app.product.modeling.schemas import (
    C1RecognitionRequest,
    C1RecognitionView,
    C7ResolveRequest,
    C7RunView,
    CategoryCreate,
    IndustryPatch,
    IndustryWrite,
    OpsDecisionRequest,
    SignalWeightUpdate,
    TemplateUpsert,
    TodoView,
)
from app.product.product_intake.models import ProductIntakeApplication
from app.product.product_intake.schemas import Actor
from app.product.product_intake.service import IntakeNotFound
from app.product.product_intake.statemachine import (
    IllegalTransition,
    RoleRequired,
)

router = APIRouter(prefix="/api", tags=["product-modeling"])


def require_operations_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, OPERATIONS)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def require_dictionary_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, DICTIONARY_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


# ---- Q2 信号权重 ----

@router.get("/admin/c1/signal-weights")
async def get_signal_weights(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_operations_view),
) -> list[dict]:
    rows = await service.list_signal_weights(session)
    return [
        {
            "signal": w.signal,
            "signal_name": w.signal_name,
            "enabled": w.enabled,
            "weight": w.weight,
            "scoring_method": w.scoring_method,
        }
        for w in rows
    ]


@router.put("/admin/c1/signal-weights")
async def put_signal_weights(
    body: SignalWeightUpdate, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        rows = await service.replace_signal_weights(session, body.rows, body.actor)
    except (service.ConfigError, WeightSumError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"updated": [w.signal for w in rows]}


# ---- Q7 行业阈值 CRUD ----

@router.get("/admin/c1/industries")
async def get_industries(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_operations_view),
) -> list[dict]:
    rows = await service.list_industries(session)
    return [
        {
            "industry": r.industry,
            "keywords": r.keywords,
            "threshold": r.threshold,
            "sensitive": r.sensitive,
            "enabled": r.enabled,
            "is_default": r.is_default,
        }
        for r in rows
    ]


@router.post("/admin/c1/industries", status_code=201)
async def post_industry(
    body: IndustryWrite, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        row = await service.create_industry(session, body.item, body.actor)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="industry already exists") from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"industry": row.industry}


@router.patch("/admin/c1/industries/{industry}")
async def patch_industry(
    industry: str, body: IndustryPatch, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        row = await service.patch_industry(session, industry, body, body.actor)
    except service.CategoryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"industry": row.industry, "threshold": row.threshold}


class _ActorBody(BaseModel):
    actor: Actor


@router.delete("/admin/c1/industries/{industry}", status_code=204)
async def delete_industry(
    industry: str, body: _ActorBody, session: AsyncSession = Depends(get_session)
):
    try:
        await service.delete_industry(session, industry, body.actor)
    except service.CategoryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.DefaultIndustryProtected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# ---- C1 识别三分支（Q1/Q3/Q4/Q5） ----

@router.post("/intakes/{intake_id}/c1-recognition", response_model=C1RecognitionView)
async def post_recognition(
    intake_id: str,
    body: C1RecognitionRequest,
    session: AsyncSession = Depends(get_session),
) -> C1RecognitionView:
    try:
        record, todo = await service.submit_recognition(session, intake_id, body)
    except IntakeNotFound as exc:
        raise HTTPException(status_code=404, detail="intake not found") from exc
    except service.RecognitionNotAllowed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.InvalidDecision as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    intake = await session.get(ProductIntakeApplication, intake_id)
    return C1RecognitionView(
        record_id=record.record_id,
        conf=record.conf,
        industry=record.industry,
        branch=record.branch,
        top_gap=record.top_gap,
        intake_status=intake.status,
        todo_id=todo.todo_id if todo else None,
    )


@router.post("/intakes/{intake_id}/ops-decision", response_model=TodoView)
async def post_ops_decision(
    intake_id: str,
    body: OpsDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> TodoView:
    try:
        todo = await service.ops_decide(session, intake_id, body)
    except IntakeNotFound as exc:
        raise HTTPException(status_code=404, detail="intake not found") from exc
    except service.TodoNotFound as exc:
        raise HTTPException(status_code=409, detail="no open ops_assist todo") from exc
    except service.InvalidDecision as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RoleRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TodoView(
        todo_id=todo.todo_id,
        todo_type=todo.todo_type,
        entity_id=todo.entity_id,
        status=todo.status,
        due_at=todo.due_at.isoformat(),
        escalated_at=todo.escalated_at.isoformat() if todo.escalated_at else None,
    )


@router.post("/admin/ops-todos/sweep")
async def post_sweep(
    body: _ActorBody, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        count = await service.escalate_due_todos(session, body.actor)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"escalated": count}


# ---- G1 类目 + 模板（最小切片） ----

@router.post("/categories", status_code=201)
async def post_category(
    body: CategoryCreate, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        row = await service.create_category(session, body)
    except service.CategoryNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"category_id": row.category_id}


@router.get("/categories")
async def get_categories(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_dictionary_view),
) -> list[dict]:
    rows = await service.list_categories(session)
    return [
        {
            "category_id": c.category_id,
            "name": c.name,
            "parent_id": c.parent_id,
            "status": c.status,
            "merged_into": c.merged_into,
            "product_count": c.product_count,
        }
        for c in rows
    ]


@router.put("/categories/{category_id}/template")
async def put_template(
    category_id: str,
    body: TemplateUpsert,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        tpl = await service.upsert_template(session, category_id, body, body.actor)
    except service.CategoryNotFound as exc:
        raise HTTPException(status_code=404, detail="category not found") from exc
    except service.InvalidDecision as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except c7.IllegalFid as exc:  # Q68
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"category_id": tpl.category_id, "status": tpl.status, "fields": len(tpl.field_list)}


# ---- C7 四层兜底 ----

@router.post("/intakes/{intake_id}/c7-runs", response_model=C7RunView)
async def post_c7_run(
    intake_id: str,
    body: C7ResolveRequest,
    session: AsyncSession = Depends(get_session),
) -> C7RunView:
    try:
        run = await service.resolve_c7(session, intake_id, body, body.actor)
    except IntakeNotFound as exc:
        raise HTTPException(status_code=404, detail="intake not found") from exc
    except service.CategoryNotFound as exc:
        raise HTTPException(status_code=404, detail="category not found") from exc
    except service.InvalidDecision as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except c7.IllegalFid as exc:  # Q68
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    candidate_ids = list(run.detail.get("candidate_ids", [])) if run.detail else []
    return C7RunView(
        run_id=run.run_id,
        layer=run.layer,
        field_list=run.field_list,
        candidate_ids=candidate_ids,
    )
