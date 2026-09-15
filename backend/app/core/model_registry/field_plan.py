"""Q85 切片：WF-02 字段池方案生成（DIM-MERGE）的进程内 LLM 调用编排。

形态沿用 Q82/Q83/Q84（extraction/pwc_build/c7_resolve）：operations 在业务
端点显式触发 → 取产品资料/敏感行业标/启用来源路由/active G2 字段（有界变量）
→ 进程内同步调模型网关 → 严格校验为去 actor 的 PlanSubmitRequest 形态
（target_atom_min/max 必须原样回传；role/source_route/fid 必须取自有界白名单；
source_ref 红线 line 14081 不允许空白；confidence 为 PT-FP-PLAN 契约内 AI 字段
故 0..1 透传，驱动 Q9 细看/Q12 Top8，与 Q83/Q84 剥离的 Q22 业务评分性质不同）
→ 整方案单候选（field_plan，product_space 锚点）经 skill7 同一条投递通道落
pending_review。PT-FP-PLAN/Q8/Q9/Q10/Q11/Q12/Q15 与 WF-02 Gate 只在
product_reviewer confirm 后由既有适配器 apply_field_plan→submit_plan 执行，
本模块一项不绕。FIELDPOOL-PLAN/DIM-SOURCE 的七路外部采集连接器属 V2，本切片
一次调用产出合并后整方案。
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.model_registry import gateway
from app.core.model_registry.schemas import FieldPlanInvokeRequest
from app.core.model_registry.seeds import SCENE_DIM_MERGE
from app.core.rbac import OPERATIONS, require_any_role
from app.core.skill7.schemas import CandidateInput, DeliverRunRequest
from app.core.skill7.service import deliver_generated_run
from app.product.fieldpool import planning
from app.product.fieldpool.models import FieldPool, FPSourceRoute
from app.product.fieldpool.service import (
    GateNotAllowed,
    ProductSpaceNotFound,
)
from app.product.product_intake.models import G2Field, ProductSpace

SYSTEM_ACTOR = Actor(id="system:llm-gateway", roles=[])


class FieldPlanInvokeState(Exception):
    pass


class FieldPlanOutputInvalid(Exception):
    pass


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


async def invoke_field_plan(
    session: AsyncSession,
    product_space_id: str,
    body: FieldPlanInvokeRequest,
    trigger_actor: Actor,
):
    require_any_role(trigger_actor, OPERATIONS)

    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)

    pool = (
        await session.scalars(
            select(FieldPool).where(FieldPool.product_space_id == product_space_id)
        )
    ).first()
    if pool is not None and pool.gate != planning.GATE_REJECTED:
        # 与 submit_plan 同口径：仅无池/被拒池可提交，approved 后不可改。
        raise GateNotAllowed(
            "LLM field plan only allowed when no pool exists or the pool was rejected"
        )

    target_min = body.target_atom_min or planning.target_atom_min_default()
    target_max = body.target_atom_max or planning.target_atom_max_default()
    if target_min > target_max:
        raise GateNotAllowed("target_atom_min must be <= target_atom_max")

    dim_min = planning.dim_min()
    dim_max = planning.dim_max()

    routes = (
        await session.scalars(
            select(FPSourceRoute)
            .where(FPSourceRoute.enabled.is_(True))
            .order_by(FPSourceRoute.sort_order, FPSourceRoute.route)
        )
    ).all()
    enabled_routes = {r.route for r in routes}

    active_rows = (
        await session.execute(
            select(G2Field.fid, G2Field.field_name).where(G2Field.status == "active")
        )
    ).all()
    active_fids = {row[0] for row in active_rows}

    profile = dict(ps.profile_snapshot or {})
    profile_lines = [f"- {key}: {value}" for key, value in profile.items()]

    variables = {
        # 模板渲染用（字符串）：
        "product_profile": "\n".join(profile_lines) or "（无）",
        "sensitive_industry": "是" if ps.sensitive_industry else "否",
        "industry_tag": ps.industry_tag or "（无）",
        "enabled_routes": "\n".join(f"- {r.route} | {r.name}" for r in routes) or "（无）",
        "active_g2_fields": (
            "\n".join(f"- {fid} | {name}" for fid, name in active_rows) or "（无）"
        ),
        "dim_range": f"{dim_min}-{dim_max}",
        "target_atom_range": f"{target_min}-{target_max}",
        # 合成替身驱动用（机读），不进模板占位：
        "_profile": {str(k): str(v) for k, v in profile.items()},
        "_sensitive": ps.sensitive_industry,
        "_industry_tag": ps.industry_tag,
        "_routes": [{"route": r.route, "name": r.name} for r in routes],
        "_active_fields": [{"fid": fid, "field_name": name} for fid, name in active_rows],
        "_dim_min": dim_min,
        "_dim_max": dim_max,
        "_target_atom_min": target_min,
        "_target_atom_max": target_max,
    }

    invocation = await gateway.invoke(session, SCENE_DIM_MERGE, variables)
    try:
        parsed = json.loads(invocation.text)
        raw_min = parsed["target_atom_min"]
        raw_max = parsed["target_atom_max"]
        raw_dims = parsed["dimensions"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FieldPlanOutputInvalid(
            f"model output is not a valid DIM-MERGE plan JSON: {exc}"
        ) from exc

    if raw_min != target_min or raw_max != target_max:
        # 目标原子数区间由触发侧给定（Q15），模型不得改。
        raise FieldPlanOutputInvalid(
            "model output target_atom_min/max must echo the triggered values exactly"
        )
    if not isinstance(raw_dims, list) or not raw_dims:
        raise FieldPlanOutputInvalid("model output dimensions must be a non-empty list")
    if len(raw_dims) > dim_max:
        # Q12 Top8 是域内越界处置；模型输出超界属结构脏数据（有界输出）。
        raise FieldPlanOutputInvalid(
            f"model output has {len(raw_dims)} dimensions, exceeding dim_max {dim_max} (Q12)"
        )

    dimensions: list[dict] = []
    seen_names: set[str] = set()
    for item in raw_dims:
        if not isinstance(item, dict):
            raise FieldPlanOutputInvalid("each dimension must be an object")
        field_name = item.get("field_name")
        if not isinstance(field_name, str) or not field_name.strip():
            raise FieldPlanOutputInvalid("each dimension requires a non-empty field_name")
        if field_name in seen_names:
            raise FieldPlanOutputInvalid(f"duplicate dimension field_name: {field_name}")
        seen_names.add(field_name)

        role = item.get("role")
        if role not in planning.DIMENSION_ROLES:
            raise FieldPlanOutputInvalid(f"unknown dimension role: {role!r}")
        source_route = item.get("source_route")
        if source_route not in enabled_routes:
            raise FieldPlanOutputInvalid(
                f"unknown or disabled source_route: {source_route!r}"
            )
        confidence = item.get("confidence")
        if not _is_number(confidence) or not 0 <= confidence <= 1:
            # PT-FP-PLAN 契约内 AI 字段（Q9/Q12 依赖）：必给 0..1，不兜底。
            raise FieldPlanOutputInvalid("each dimension requires confidence in [0, 1]")
        source_ref = item.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref.strip():
            # line 14081 依据红线：缺依据不允许落候选，禁止模型编造。
            raise FieldPlanOutputInvalid("each dimension requires a non-empty source_ref")

        dim = {
            "field_name": field_name,
            "role": role,
            "source_route": source_route,
            "confidence": float(confidence),
            "source_ref": source_ref.strip(),
        }

        fid = item.get("fid")
        if fid is not None:
            if not isinstance(fid, str) or fid == "-" or fid not in active_fids:
                # Q68：'-' 非法；幻觉 fid 不允许，新字段必须省略 fid 并给 definition。
                raise FieldPlanOutputInvalid(
                    f"dimension fid must reference an active G2 field, got {fid!r}"
                )
            dim["fid"] = fid

        similarity = item.get("similarity")
        if similarity is not None:
            if not _is_number(similarity) or not 0 <= similarity <= 1:
                raise FieldPlanOutputInvalid("similarity must be a number in [0, 1]")
            dim["similarity"] = float(similarity)
        related_fid = item.get("related_fid")
        if related_fid is not None:
            if not isinstance(related_fid, str) or not related_fid.strip():
                raise FieldPlanOutputInvalid("related_fid must be a non-empty string")
            dim["related_fid"] = related_fid.strip()
        definition = item.get("definition")
        if isinstance(definition, str) and definition.strip():
            dim["definition"] = definition.strip()

        dimensions.append(dim)

    payload = {
        "target_atom_min": target_min,
        "target_atom_max": target_max,
        "dimensions": dimensions,
    }
    body = DeliverRunRequest(
        skill_id=SCENE_DIM_MERGE,
        product_space_id=product_space_id,
        input={
            "profile_key_count": len(profile),
            "sensitive_industry": ps.sensitive_industry,
            "enabled_route_count": len(routes),
            "active_g2_field_count": len(active_fids),
            "dimension_count": len(dimensions),
        },
        output=payload,
        candidates=[CandidateInput(target_type="field_plan", payload=payload)],
        input_tokens=invocation.input_tokens,
        output_tokens=invocation.output_tokens,
        actor=SYSTEM_ACTOR,
    )
    return await deliver_generated_run(
        session,
        body,
        model_id=invocation.model_id,
        input_cost=invocation.input_cost,
        output_cost=invocation.output_cost,
        currency_code=invocation.currency_code,
    )
