"""Q83 切片：PWC-BUILDER 组合生成的进程内 LLM 调用编排。

形态沿用 Q82（extraction.py）：operations 在业务端点显式触发 → 取 approved
原子/active 目的/库容现状 → 进程内同步调模型网关 → 校验为漏斗 combo 形态
（去评分，Q22b）→ 一条组合一条 pwc_combo 候选经 skill7 同一条投递通道落
pending_review；M5 漏斗全部规则只在 product_reviewer confirm 后由适配器执行。

Q71 restock_auto 的 SkillRun(requested) 由 Q87 M8 worker 自动消费：HTTP 端点
走 invoke_pwc_build（operations 闸保留），worker 走 invoke_pwc_build_for_restock
（系统内部入口，不过角色闸，子 run input 回链 restock_request_id）。
"""

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.model_registry import gateway
from app.core.model_registry.seeds import SCENE_PWC_BUILDER
from app.core.rbac import OPERATIONS, require_any_role
from app.core.skill7.schemas import CandidateInput, DeliverRunRequest
from app.core.skill7.service import deliver_generated_run
from app.product.atom.atom_rules import ATOM_APPROVED
from app.product.atom.models import ProductAtomInstance
from app.product.condition import pwc_rules
from app.product.condition.models import ConditionPackage, ContentGoal
from app.product.condition.service import (
    PoolNotApproved,
    ProductSpaceNotFound,
    get_pool_config,
)
from app.product.fieldpool.models import FieldPool
from app.product.product_intake.models import ProductSpace

SYSTEM_ACTOR = Actor(id="system:llm-gateway", roles=[])


class PwcBuildNotReady(Exception):
    pass


class PwcBuildOutputInvalid(Exception):
    pass


async def invoke_pwc_build(session: AsyncSession, product_space_id: str, trigger_actor: Actor):
    require_any_role(trigger_actor, OPERATIONS)
    return await _run_pwc_build(session, product_space_id)


async def invoke_pwc_build_for_restock(
    session: AsyncSession, product_space_id: str, *, restock_request_id: str
):
    """Q87：restock worker 系统内部入口，不过 HTTP 角色闸（受信进程内调度）。"""
    return await _run_pwc_build(
        session, product_space_id, restock_request_id=restock_request_id
    )


async def _run_pwc_build(
    session: AsyncSession,
    product_space_id: str,
    *,
    restock_request_id: str | None = None,
):
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)

    pool = (
        await session.scalars(
            select(FieldPool).where(FieldPool.product_space_id == product_space_id)
        )
    ).first()
    if pool is None or pool.gate != "approved":
        raise PoolNotApproved("PWC LLM build requires an approved FieldPool")

    atoms = (
        await session.scalars(
            select(ProductAtomInstance).where(
                ProductAtomInstance.product_space_id == product_space_id,
                ProductAtomInstance.tenant_id == ps.tenant_id,
                ProductAtomInstance.status == ATOM_APPROVED,
            )
        )
    ).all()
    dim_of = {a.atom_id: a.dimension_id for a in atoms}
    if len({d for d in dim_of.values() if d}) < 2:
        # 组合必须跨 ≥2 维度（M5 漏斗同口径）；素材不足不调模型。
        raise PwcBuildNotReady(
            "PWC LLM build requires approved atoms spanning at least two field dimensions"
        )

    active_goals = [
        g.code
        for g in (
            await session.scalars(
                select(ContentGoal).where(ContentGoal.status == "active")
            )
        ).all()
    ]
    goal_set = set(active_goals)

    pool_cfg = await get_pool_config(session, product_space_id)
    ready_count = (
        await session.scalar(
            select(func.count(ConditionPackage.pwc_id)).where(
                ConditionPackage.product_space_id == product_space_id,
                ConditionPackage.gate_status == pwc_rules.GATE_APPROVED,
                ConditionPackage.status == pwc_rules.PWC_READY,
            )
        )
    ) or 0
    batch_limit = pwc_rules.single_run_max()

    atom_lines = [
        f"- {a.atom_id} | {a.dimension_id} | {a.content}" for a in atoms
    ]
    variables = {
        # 模板渲染用（字符串）：
        "approved_atoms": "\n".join(atom_lines),
        "active_goals": "\n".join(f"- {code}" for code in active_goals) or "（无）",
        "capacity": "null" if pool_cfg["capacity"] is None else str(pool_cfg["capacity"]),
        "ready_count": str(ready_count),
        "target_platforms": ", ".join(pool_cfg["target_platforms"]) or "（未配置）",
        "batch_limit": str(batch_limit),
        # 合成替身驱动用（机读），不进模板占位：
        "_approved_atoms": [
            {"atom_id": a.atom_id, "dimension_id": a.dimension_id} for a in atoms
        ],
        "_active_goals": active_goals,
    }

    invocation = await gateway.invoke(session, SCENE_PWC_BUILDER, variables)
    try:
        parsed = json.loads(invocation.text)
        raw_combos = parsed["combos"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PwcBuildOutputInvalid(
            f"model output is not a valid PWC combo JSON: {exc}"
        ) from exc
    if not isinstance(raw_combos, list):
        raise PwcBuildOutputInvalid("model output combos must be a list")
    if not raw_combos:
        raise PwcBuildOutputInvalid("model output combos must be non-empty")
    if len(raw_combos) > batch_limit:
        raise PwcBuildOutputInvalid(
            f"model output has {len(raw_combos)} combos, exceeding batch cap {batch_limit} (Q21)"
        )

    combos: list[dict] = []
    seen: set[frozenset] = set()
    for item in raw_combos:
        if not isinstance(item, dict):
            raise PwcBuildOutputInvalid("each combo must be an object")
        raw_ids = item.get("atom_ids")
        raw_goals = item.get("goals", [])
        if not isinstance(raw_ids, list) or not raw_ids:
            raise PwcBuildOutputInvalid("combo atom_ids must be a non-empty list")
        atom_ids = [str(aid) for aid in raw_ids]
        if len(set(atom_ids)) < 2 or len(set(atom_ids)) != len(atom_ids):
            raise PwcBuildOutputInvalid("each combo needs at least 2 distinct atoms")
        unknown = [aid for aid in atom_ids if aid not in dim_of]
        if unknown:
            raise PwcBuildOutputInvalid(
                f"combo uses atoms not approved for this product space: {sorted(unknown)}"
            )
        if len({dim_of[aid] for aid in atom_ids if dim_of[aid]}) < 2:
            raise PwcBuildOutputInvalid("each combo must span at least two field dimensions")
        if not isinstance(raw_goals, list):
            raise PwcBuildOutputInvalid("combo goals must be a list")
        goals = [str(g) for g in raw_goals]
        unknown_goals = [g for g in goals if g not in goal_set]
        if unknown_goals:
            raise PwcBuildOutputInvalid(
                f"combo uses unknown or inactive goals: {sorted(unknown_goals)}"
            )
        # 评分（logic/fit/weight）即便模型回带也不透传（Q83-3，Q22b 子分缺失转人工）。
        id_set = frozenset(atom_ids)
        if id_set in seen:
            # 逐候选落库后漏斗的同批去重不再跨候选生效，机械去重前置（Q83-2）。
            continue
        seen.add(id_set)
        combos.append({"atom_ids": atom_ids, "goals": goals})

    if not combos:
        raise PwcBuildOutputInvalid("model output combos are all duplicates")

    run_input = {
        "approved_atom_count": len(atoms),
        "dimension_count": len({d for d in dim_of.values() if d}),
        "active_goal_count": len(active_goals),
        "capacity": pool_cfg["capacity"],
        "ready_count": ready_count,
    }
    if restock_request_id is not None:
        # Q87：纯追加认领——子 llm_auto run 回链 requested 信号行（信号行不 mutate）。
        run_input["restock_request_id"] = restock_request_id
    body = DeliverRunRequest(
        skill_id=SCENE_PWC_BUILDER,
        product_space_id=product_space_id,
        input=run_input,
        output={"combos": combos},
        candidates=[
            CandidateInput(target_type="pwc_combo", payload={"combos": [combo]})
            for combo in combos
        ],
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
