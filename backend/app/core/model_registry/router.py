"""模型注册表/场景路由/Key/Prompt 管理端点 + CAT-RECOG 试点触发（Q67/Q82）。

角色（Q82 实现补登）：模型/Key/Prompt=platform_admin 红线操作；场景路由
运营可改（Q67 原文"运营可改不动代码"）= operations|platform_admin；试点触发
= operations（与 skill7 投递同档）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.db import get_session
from app.core.model_registry import c7_resolve, extraction, gateway
from app.core.model_registry.schemas import (
    AIModelCreate,
    AIModelPatch,
    AIModelView,
    C7ResolveInvokeRequest,
    KeyCreate,
    KeyView,
    PromptPublish,
    PromptVersionDetail,
    PromptVersionView,
    PromptView,
    RecognizeInvokeRequest,
    SceneRouteUpsert,
    SceneRouteView,
)
from app.core.rbac import (
    OPERATIONS,
    PLATFORM_ADMIN,
    PermissionDenied,
    require_any_role,
)
from app.product.modeling import c7 as c7_rules
from app.product.modeling.service import CategoryNotFound

router = APIRouter(tags=["model-registry"])


def require_models_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def require_scene_routes_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, OPERATIONS, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def require_prompts_view(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    # Q113：Skill Prompt 三读口与发布写口（docs/05:233）同组，仅 platform_admin；
    # 单版本详情含 template+variables 全文，按 ai-models 同型平台级敏感配置处理。
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def _http409(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


@router.post("/api/admin/ai-models", response_model=AIModelView, status_code=201)
async def create_model(body: AIModelCreate, session: AsyncSession = Depends(get_session)):
    try:
        model = await gateway.create_model(session, body)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except gateway.ModelConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return AIModelView(
        model_id=model.model_id, model_code=model.model_code, provider=model.provider,
        capability=model.capability,
        input_price_per_1m=float(model.input_price_per_1m),
        output_price_per_1m=float(model.output_price_per_1m),
        currency_code=model.currency_code,
        daily_budget=float(model.daily_budget) if model.daily_budget is not None else None,
        status=model.status, fallback_model_id=model.fallback_model_id,
    )


@router.get("/api/admin/ai-models", response_model=list[AIModelView])
async def list_models(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_models_view),
):
    rows = await gateway.list_models(session)
    return [
        AIModelView(
            model_id=m.model_id, model_code=m.model_code, provider=m.provider,
            capability=m.capability,
            input_price_per_1m=float(m.input_price_per_1m),
            output_price_per_1m=float(m.output_price_per_1m),
            currency_code=m.currency_code,
            daily_budget=float(m.daily_budget) if m.daily_budget is not None else None,
            status=m.status, fallback_model_id=m.fallback_model_id, has_active_key=has_key,
        )
        for m, has_key in rows
    ]


@router.patch("/api/admin/ai-models/{model_id}", response_model=AIModelView)
async def patch_model(
    model_id: str, body: AIModelPatch, session: AsyncSession = Depends(get_session)
):
    try:
        model = await gateway.patch_model(session, model_id, body)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except gateway.ModelNotFound as exc:
        raise HTTPException(status_code=404, detail=f"model {exc} not found") from exc
    except gateway.ModelConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    has_active_key = any(k.status == "active" for k in await gateway.list_keys(session, model_id))
    await session.commit()
    return AIModelView(
        model_id=model.model_id, model_code=model.model_code, provider=model.provider,
        capability=model.capability,
        input_price_per_1m=float(model.input_price_per_1m),
        output_price_per_1m=float(model.output_price_per_1m),
        currency_code=model.currency_code,
        daily_budget=float(model.daily_budget) if model.daily_budget is not None else None,
        status=model.status, fallback_model_id=model.fallback_model_id,
        has_active_key=has_active_key,
    )


@router.post(
    "/api/admin/ai-models/{model_id}/keys", response_model=KeyView, status_code=201
)
async def create_key(
    model_id: str, body: KeyCreate, session: AsyncSession = Depends(get_session)
):
    try:
        key = await gateway.create_key(session, model_id, body)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except gateway.ModelNotFound as exc:
        raise HTTPException(status_code=404, detail=f"model {exc} not found") from exc
    await session.commit()
    return KeyView(
        key_id=key.key_id, model_id=model_id, fingerprint=key.fingerprint, status=key.status
    )


@router.post("/api/admin/ai-model-keys/{key_id}/revoke", response_model=KeyView)
async def revoke_key_post(
    key_id: str, body: RecognizeInvokeRequest, session: AsyncSession = Depends(get_session)
):
    try:
        key = await gateway.revoke_key(session, key_id, body.actor)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except gateway.ModelNotFound as exc:
        raise HTTPException(status_code=404, detail=f"key {exc} not found") from exc
    await session.commit()
    return KeyView(
        key_id=key.key_id, model_id=key.model_id, fingerprint=key.fingerprint,
        status=key.status,
    )


@router.get("/api/admin/ai-models/{model_id}/keys", response_model=list[KeyView])
async def list_keys(model_id: str, session: AsyncSession = Depends(get_session)):
    rows = await gateway.list_keys(session, model_id)
    return [
        KeyView(key_id=k.key_id, model_id=model_id, fingerprint=k.fingerprint, status=k.status)
        for k in rows
    ]


@router.put("/api/admin/ai-scene-routes/{scene}", response_model=SceneRouteView)
async def upsert_route(
    scene: str, body: SceneRouteUpsert, session: AsyncSession = Depends(get_session)
):
    try:
        route = await gateway.upsert_route(session, scene, body)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except gateway.ModelConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return SceneRouteView(scene=route.scene, model_id=route.model_id)


@router.get("/api/admin/ai-scene-routes", response_model=list[SceneRouteView])
async def list_routes(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_scene_routes_view),
):
    rows = await gateway.list_routes(session)
    return [SceneRouteView(scene=r.scene, model_id=r.model_id) for r in rows]


@router.post(
    "/api/admin/skill-prompts/{skill_id}/versions",
    response_model=PromptVersionView,
    status_code=201,
)
async def publish_prompt(
    skill_id: str, body: PromptPublish, session: AsyncSession = Depends(get_session)
):
    try:
        row = await gateway.publish_prompt(session, skill_id, body)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await session.commit()
    return PromptVersionView(
        version_id=row.version_id, skill_id=skill_id, version=row.version,
        change_note=row.change_note, created_by=row.created_by,
    )


@router.get("/api/admin/skill-prompts", response_model=list[PromptView])
async def list_prompts(
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_prompts_view),
):
    from sqlalchemy import select

    from app.core.model_registry.models import SkillPrompt

    rows = (await session.scalars(select(SkillPrompt).order_by(SkillPrompt.skill_id))).all()
    return [PromptView(skill_id=r.skill_id, current_version=r.current_version) for r in rows]


@router.get(
    "/api/admin/skill-prompts/{skill_id}/versions",
    response_model=list[PromptVersionView],
)
async def list_prompt_versions(
    skill_id: str,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_prompts_view),
):
    rows = await gateway.list_prompt_versions(session, skill_id)
    return [
        PromptVersionView(
            version_id=r.version_id, skill_id=skill_id, version=r.version,
            change_note=r.change_note, created_by=r.created_by,
        )
        for r in rows
    ]


@router.get(
    "/api/admin/skill-prompts/{skill_id}/versions/{version}",
    response_model=PromptVersionDetail,
)
async def get_prompt_version(
    skill_id: str,
    version: str,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_prompts_view),
):
    from sqlalchemy import select

    from app.core.model_registry.models import SkillPromptVersion

    row = (await session.scalars(
        select(SkillPromptVersion).where(
            SkillPromptVersion.skill_id == skill_id, SkillPromptVersion.version == version
        )
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail="prompt version not found")
    return PromptVersionDetail(
        version_id=row.version_id, skill_id=skill_id, version=row.version,
        change_note=row.change_note, created_by=row.created_by,
        template=row.template, variables=row.variables,
    )


# ---------- CAT-RECOG 试点（Q82-1/2） -------------------------------------------

@router.post("/api/intakes/{intake_id}/c1-recognition/llm-invoke", status_code=201)
async def invoke_c1_recognition(
    intake_id: str,
    body: RecognizeInvokeRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        run, candidates = await extraction.invoke_c1_recognition(
            session, intake_id, body.actor
        )
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except extraction.RecognitionInvokeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except extraction.RecognitionInvokeState as exc:
        raise _http409(str(exc))
    except gateway.ModelNotFound as exc:
        raise HTTPException(status_code=404, detail=f"model {exc} not found") from exc
    except gateway.ModelUnavailable as exc:
        raise _http409(str(exc))
    except gateway.ModelConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except gateway.GenerationUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except extraction.ExtractionOutputInvalid as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await session.commit()
    return {
        "run_id": run.run_id,
        "source": run.source,
        "model_id": run.model_id,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "candidates": [
            {"candidate_id": c.candidate_id, "state": c.state, "target_type": c.target_type}
            for c in candidates
        ],
    }


# ---------- C7 Layer4 TYPE-MATCH（Q84） ------------------------------------------

@router.post("/api/intakes/{intake_id}/c7/llm-resolve", status_code=201)
async def invoke_c7_resolve(
    intake_id: str,
    body: C7ResolveInvokeRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        run, candidates = await c7_resolve.invoke_c7_resolve(
            session, intake_id, body, body.actor
        )
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except c7_resolve.C7ResolveInvokeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CategoryNotFound as exc:
        raise HTTPException(status_code=404, detail=f"category {exc} not found") from exc
    except c7_resolve.C7ResolveInvokeState as exc:
        raise _http409(str(exc))
    except gateway.ModelUnavailable as exc:
        raise _http409(str(exc))
    except gateway.ModelConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except c7_rules.IllegalFid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except gateway.GenerationUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except c7_resolve.C7ResolveOutputInvalid as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await session.commit()
    return {
        "run_id": run.run_id,
        "source": run.source,
        "model_id": run.model_id,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "candidates": [
            {"candidate_id": c.candidate_id, "state": c.state, "target_type": c.target_type}
            for c in candidates
        ],
    }
