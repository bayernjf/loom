"""模型网关：注册表/路由/Key/Prompt 管理与进程内同步调用（Q67/Q82）。

调用形态（Q82-2）：业务侧在进程内同步 invoke，产出仍走 skill7 同一条投递
通道落 pending_review，AI 不静默生效；本模块不碰任何业务 Gate。
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from string import Template

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.model_registry import crypto, drivers
from app.core.model_registry.models import (
    AIModel,
    AIModelKey,
    AISceneRoute,
    SkillPrompt,
    SkillPromptVersion,
)
from app.core.model_registry.schemas import (
    AIModelCreate,
    AIModelPatch,
    KeyCreate,
    PromptPublish,
    SceneRouteUpsert,
)
from app.core.rbac import OPERATIONS, PLATFORM_ADMIN, require_any_role
from app.core.skill7.models import SkillRun

PLATFORM_TENANT = "_platform"


class ModelNotFound(Exception):
    pass


class ModelConfigError(Exception):
    """场景路由/Prompt/Key 等配置缺失或非法。"""


class ModelUnavailable(Exception):
    """模型停用且无可用 fallback，或日预算耗尽（Q82 实现补登：硬停）。"""


class GenerationUpstreamError(Exception):
    pass


# ---------- 模型注册表 ----------------------------------------------------------

async def create_model(session: AsyncSession, body: AIModelCreate) -> AIModel:
    require_any_role(body.actor, PLATFORM_ADMIN)
    existing = (await session.scalars(
        select(AIModel).where(AIModel.model_code == body.model_code)
    )).first()
    if existing is not None:
        raise ModelConfigError(f"model_code {body.model_code!r} already exists")
    if body.fallback_model_id is not None:
        # 自引用 fallback 在创建时无法自洽；先建行后用 patch 挂。
        raise ModelConfigError("fallback_model_id cannot be set at creation")
    model = AIModel(
        model_code=body.model_code,
        provider=body.provider,
        input_price_per_1m=body.input_price_per_1m,
        output_price_per_1m=body.output_price_per_1m,
        currency_code=body.currency_code,
        daily_budget=body.daily_budget,
        created_by=body.actor.id,
        updated_by=body.actor.id,
    )
    session.add(model)
    await session.flush()
    await append_audit(
        session, tenant_id=PLATFORM_TENANT, actor_id=body.actor.id,
        actor_roles=body.actor.roles, action="ai_model.create",
        entity_type="ai_model", entity_id=model.model_id,
        detail={"model_code": body.model_code, "provider": body.provider},
    )
    return model


async def patch_model(session: AsyncSession, model_id: str, body: AIModelPatch) -> AIModel:
    require_any_role(body.actor, PLATFORM_ADMIN)
    model = await session.get(AIModel, model_id)
    if model is None:
        raise ModelNotFound(model_id)
    if body.fallback_model_id is not None:
        if body.fallback_model_id == model_id:
            raise ModelConfigError("fallback_model_id cannot point to the model itself")
        target = await session.get(AIModel, body.fallback_model_id)
        if target is None:
            raise ModelConfigError("fallback model does not exist")
    changes = body.model_dump(exclude={"actor"}, exclude_unset=True)
    for key, value in changes.items():
        setattr(model, key, value)
    model.updated_by = body.actor.id
    await append_audit(
        session, tenant_id=PLATFORM_TENANT, actor_id=body.actor.id,
        actor_roles=body.actor.roles, action="ai_model.update",
        entity_type="ai_model", entity_id=model_id, detail=changes,
    )
    return model


async def list_models(session: AsyncSession) -> list[tuple[AIModel, bool]]:
    rows = (await session.scalars(select(AIModel).order_by(AIModel.model_code))).all()
    active_key_models = {
        row[0]
        for row in (await session.execute(
            select(AIModelKey.model_id).where(AIModelKey.status == "active")
        )).all()
    }
    return [(m, m.model_id in active_key_models) for m in rows]


# ---------- API Key（outbound，Q82-3） -----------------------------------------

async def create_key(session: AsyncSession, model_id: str, body: KeyCreate) -> AIModelKey:
    require_any_role(body.actor, PLATFORM_ADMIN)
    model = await session.get(AIModel, model_id)
    if model is None:
        raise ModelNotFound(model_id)
    old = (await session.scalars(
        select(AIModelKey)
        .where(AIModelKey.model_id == model_id, AIModelKey.status == "active")
        .order_by(AIModelKey.created_at.desc())
    )).all()
    for row in old:
        row.status = "revoked"
        row.revoked_by = body.actor.id
        row.revoked_at = datetime.now(UTC)
    key = AIModelKey(
        model_id=model_id,
        ciphertext=crypto.encrypt(body.secret),
        fingerprint=crypto.fingerprint(body.secret),
        created_by=body.actor.id,
    )
    session.add(key)
    await session.flush()
    await append_audit(
        session, tenant_id=PLATFORM_TENANT, actor_id=body.actor.id,
        actor_roles=body.actor.roles, action="ai_model_key.rotate",
        entity_type="ai_model_key", entity_id=key.key_id,
        detail={"model_id": model_id, "fingerprint": key.fingerprint, "revoked": len(old)},
    )
    return key


async def revoke_key(session: AsyncSession, key_id: str, actor) -> AIModelKey:
    require_any_role(actor, PLATFORM_ADMIN)
    key = await session.get(AIModelKey, key_id)
    if key is None:
        raise ModelNotFound(key_id)
    if key.status == "active":
        key.status = "revoked"
        key.revoked_by = actor.id
        key.revoked_at = datetime.now(UTC)
    await append_audit(
        session, tenant_id=PLATFORM_TENANT, actor_id=actor.id,
        actor_roles=actor.roles, action="ai_model_key.revoke",
        entity_type="ai_model_key", entity_id=key_id,
        detail={"model_id": key.model_id},
    )
    return key


async def list_keys(session: AsyncSession, model_id: str) -> list[AIModelKey]:
    return list((await session.scalars(
        select(AIModelKey)
        .where(AIModelKey.model_id == model_id)
        .order_by(AIModelKey.created_at.desc())
    )).all())


async def _active_key_secret(session: AsyncSession, model_id: str) -> str:
    key = (await session.scalars(
        select(AIModelKey)
        .where(AIModelKey.model_id == model_id, AIModelKey.status == "active")
        .order_by(AIModelKey.created_at.desc())
    )).first()
    if key is None:
        raise ModelConfigError(f"no active API key for model {model_id}")
    return crypto.decrypt(key.ciphertext)


# ---------- 场景路由（运营可改，Q67） -------------------------------------------

async def upsert_route(session: AsyncSession, scene: str, body: SceneRouteUpsert) -> AISceneRoute:
    require_any_role(body.actor, OPERATIONS, PLATFORM_ADMIN)
    model = await session.get(AIModel, body.model_id)
    if model is None:
        raise ModelConfigError("routed model does not exist")
    route = await session.get(AISceneRoute, scene)
    if route is None:
        route = AISceneRoute(scene=scene, model_id=body.model_id, updated_by=body.actor.id)
        session.add(route)
    else:
        route.model_id = body.model_id
        route.updated_by = body.actor.id
    await append_audit(
        session, tenant_id=PLATFORM_TENANT, actor_id=body.actor.id,
        actor_roles=body.actor.roles, action="ai_scene_route.update",
        entity_type="ai_scene_route", entity_id=scene,
        detail={"model_id": body.model_id},
    )
    return route


async def list_routes(session: AsyncSession) -> list[AISceneRoute]:
    return list((await session.scalars(select(AISceneRoute).order_by(AISceneRoute.scene))).all())


# ---------- Prompt 版本化（07 §7.3，Q82-4） -------------------------------------

async def publish_prompt(session: AsyncSession, skill_id: str, body: PromptPublish) -> SkillPromptVersion:
    require_any_role(body.actor, PLATFORM_ADMIN)
    pointer = await session.get(SkillPrompt, skill_id)
    if pointer is None:
        version = "v0.1"
        pointer = SkillPrompt(skill_id=skill_id, current_version=version, updated_by=body.actor.id)
        session.add(pointer)
    else:
        minor = int(pointer.current_version.split(".", 1)[1]) + 1
        version = f"v0.{minor}"
        pointer.current_version = version
        pointer.updated_by = body.actor.id
    row = SkillPromptVersion(
        skill_id=skill_id,
        version=version,
        template=body.template,
        change_note=body.change_note,
        variables=body.variables,
        created_by=body.actor.id,
    )
    session.add(row)
    await session.flush()
    await append_audit(
        session, tenant_id=PLATFORM_TENANT, actor_id=body.actor.id,
        actor_roles=body.actor.roles, action="skill_prompt.publish",
        entity_type="skill_prompt", entity_id=skill_id,
        detail={"version": version, "change_note": body.change_note},
    )
    return row


async def list_prompt_versions(session: AsyncSession, skill_id: str) -> list[SkillPromptVersion]:
    return list((await session.scalars(
        select(SkillPromptVersion)
        .where(SkillPromptVersion.skill_id == skill_id)
        .order_by(SkillPromptVersion.created_at.desc(), SkillPromptVersion.version_id.desc())
    )).all())


async def _render_current_prompt(session: AsyncSession, scene: str, variables: dict) -> str:
    pointer = await session.get(SkillPrompt, scene)
    if pointer is None:
        raise ModelConfigError(f"no prompt published for scene {scene!r}")
    version = (await session.scalars(
        select(SkillPromptVersion).where(
            SkillPromptVersion.skill_id == scene,
            SkillPromptVersion.version == pointer.current_version,
        )
    )).first()
    if version is None:  # pragma: no cover - 指针必有版本行
        raise ModelConfigError(f"prompt version {pointer.current_version} missing")
    try:
        return Template(version.template).substitute(variables)
    except KeyError as exc:
        raise ModelConfigError(f"prompt template variable missing: {exc.args[0]}") from exc


# ---------- 调用 ----------------------------------------------------------------

@dataclass(frozen=True)
class Invocation:
    model_id: str
    model_code: str
    provider: str
    text: str
    input_tokens: int
    output_tokens: int
    input_cost: Decimal
    output_cost: Decimal
    currency_code: str | None


def _cost(price_per_1m: Decimal, tokens: int) -> Decimal:
    return (Decimal(price_per_1m) * Decimal(tokens) / Decimal(1_000_000)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )


async def spend_today(session: AsyncSession, model_id: str) -> Decimal:
    today = datetime.now(UTC).date()
    total = await session.scalar(
        select(func.coalesce(func.sum(SkillRun.input_cost + SkillRun.output_cost), 0)).where(
            SkillRun.model_id == model_id,
            cast(SkillRun.created_at, Date) == today,
        )
    )
    return Decimal(total or 0)


async def _resolve_model(session: AsyncSession, scene: str) -> AIModel:
    route = await session.get(AISceneRoute, scene)
    if route is None:
        raise ModelConfigError(f"no model route for scene {scene!r}")
    model = await session.get(AIModel, route.model_id)
    if model is None:  # pragma: no cover - FK 存在性兜底
        raise ModelConfigError(f"routed model {route.model_id} missing")
    if model.status == "active":
        return model
    if model.fallback_model_id:
        fallback = await session.get(AIModel, model.fallback_model_id)
        if fallback is not None and fallback.status == "active":
            return fallback
    raise ModelUnavailable(f"model for scene {scene!r} disabled without active fallback")


async def invoke(session: AsyncSession, scene: str, variables: dict) -> Invocation:
    model = await _resolve_model(session, scene)
    budget = model.daily_budget
    if budget is not None and await spend_today(session, model.model_id) >= Decimal(str(budget)):
        raise ModelUnavailable(f"daily budget exhausted for model {model.model_code!r}")

    user_message = await _render_current_prompt(session, scene, variables)
    kwargs: dict = {"model_code": model.model_code, "provider": model.provider}
    if model.provider != "synthetic":
        kwargs["api_key"] = await _active_key_secret(session, model.model_id)
    try:
        result = await drivers.driver_for(model.provider).generate(
            scene=scene, user_message=user_message, variables=variables, **kwargs
        )
    except drivers.DriverError as exc:
        raise GenerationUpstreamError(str(exc)) from exc

    return Invocation(
        model_id=model.model_id,
        model_code=model.model_code,
        provider=model.provider,
        text=result.text,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        input_cost=_cost(Decimal(model.input_price_per_1m), result.input_tokens),
        output_cost=_cost(Decimal(model.output_price_per_1m), result.output_tokens),
        currency_code=model.currency_code,
    )
