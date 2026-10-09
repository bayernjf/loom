"""候选 confirmed/modified 后的落库适配器（Q76-3）。

key = candidate.target_type；适配器只调用既有业务服务，不绕过任何
预筛/合规/评分/限量/Gate。已接入：pwc_combo（WF-04）、field_plan（WF-02，Q78）、
c1_recognition（WF-01，Q79）、atom_batch（WF-03，Q80）、c7_layer4（WF-01，Q81）、
package_draft（WF-07 AI 选包，Q328）。
"""

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.skill7.models import SkillCandidate


async def apply_pwc_combo(
    session: AsyncSession, candidate: SkillCandidate, actor: Actor
) -> list[str]:
    # 延迟导入：condition 包在 service 层反向调用 skill7 的补货函数，避免环。
    from app.product.condition import service as pwc_service
    from app.product.condition.schemas import ComboItem, FunnelRequest

    payload = candidate.payload
    body = FunnelRequest(
        combos=[ComboItem(**combo) for combo in payload["combos"]],
        batch_size=payload.get("batch_size"),
        source="ai",
        actor=actor,
    )
    created = await pwc_service.run_funnel(
        session, candidate.product_space_id, body, actor
    )
    return [p.pwc_id for p in created]


async def apply_field_plan(
    session: AsyncSession, candidate: SkillCandidate, actor: Actor
) -> list[str]:
    # Q78：DIM-MERGE 整方案候选 → 既有 fieldpool.submit_plan，
    # PT-FP-PLAN/Q8/Q9/Q10/Q12 全部在既有服务内执行，落 pending_gate 走 WF-02 Gate。
    from app.product.fieldpool import service as fp_service
    from app.product.fieldpool.schemas import PlanSubmitRequest

    data = dict(candidate.payload)
    data.pop("actor", None)
    body = PlanSubmitRequest(**data, actor=actor)
    pool = await fp_service.submit_plan(
        session, candidate.product_space_id, body, actor
    )
    return [pool.pool_id]


CandidateAdapter = Callable[[AsyncSession, SkillCandidate, Actor], Awaitable[list[str]]]


async def apply_c1_recognition(
    session: AsyncSession, candidate: SkillCandidate, actor: Actor
) -> list[str]:
    # Q79：CAT-RECOG 识别整结果候选 → 既有 modeling.submit_recognition，
    # Q1 三分支机械逻辑（direct_approve/ops_assist/cold_start）一字不改。
    from app.product.modeling import service as modeling_service
    from app.product.modeling.schemas import C1RecognitionRequest

    data = dict(candidate.payload)
    data.pop("actor", None)
    body = C1RecognitionRequest(**data, actor=actor)
    record, _todo = await modeling_service.submit_recognition(
        session, candidate.intake_id, body
    )
    return [record.record_id]


async def apply_atom_batch(
    session: AsyncSession, candidate: SkillCandidate, actor: Actor
) -> list[str]:
    # Q80：CONFLICT-PRECHECK 整批单候选 → 既有 atom.submit_batch（强制 source=ai），
    # Q14/Q15/同批去重/维度归属/line 11189 事实唯一/Q17/line 840 全部在既有服务执行。
    from app.product.atom import service as atom_service
    from app.product.atom.schemas import BatchSubmitRequest

    data = dict(candidate.payload)
    data.pop("actor", None)
    data.pop("source", None)
    # Q86：_embeddings 为编排层机读键（normalized→向量），不属 BatchSubmitRequest。
    embeddings = data.pop("_embeddings", None)
    body = BatchSubmitRequest(**data, source="ai", actor=actor)
    batch = await atom_service.submit_batch(
        session, candidate.product_space_id, body, actor, embeddings=embeddings
    )
    return [batch.batch_id]


async def apply_c7_layer4(
    session: AsyncSession, candidate: SkillCandidate, actor: Actor
) -> list[str]:
    # Q81：TYPE-MATCH 整 C7 解析单候选 → 既有 modeling.resolve_c7，
    # L1→L4 机械判定（Q6 覆盖率/Q68 fid 拦截/L4 候选落库）一项不绕；
    # 实际落在 L1/2/3 时 l4_proposals 自然不生效。Q13 转正 Gate 不变。
    from app.product.modeling import service as modeling_service
    from app.product.modeling.schemas import C7ResolveRequest

    data = dict(candidate.payload)
    data.pop("actor", None)
    body = C7ResolveRequest(**data, actor=actor)
    run = await modeling_service.resolve_c7(
        session, candidate.intake_id, body, actor
    )
    return [run.run_id]


async def apply_package_draft(
    session: AsyncSession, candidate: SkillCandidate, actor: Actor
) -> list[str]:
    """Q328（WF-07，D3/D4 甲，D5＝Package 草稿）：AI 选包候选 confirmed/modified 后落库前校验。

    - 字典强校验：候选值逐一命中既有权威字典（ContentGoal active codes、
      Q43 17 池 struct/tone/style active options），不命中即 422（越字典值禁落）。
    - **不写包表、不绕过包 Gate**：采用后的预填（goal/struct/tone/style →
      包创建/更新表单）在前端完成，走既有 layer_strategy 包 create/update 审批；
      本适配器只做终态校验并留痕（applied_refs＝命中的候选值引用）。
    """
    from app.core.pool_options.models import ACTIVE, PoolOption

    # 延迟导入防环：service 顶层已 import 本模块的 ADAPTERS。
    from app.core.skill7.service import InvalidCandidatePayload
    from app.product.condition.models import ContentGoal

    payload = candidate.payload
    if not isinstance(payload, dict) or not payload:
        raise InvalidCandidatePayload("package_draft payload must be a non-empty dict")

    goal_codes = {
        code
        for (code,) in (
            await session.execute(
                select(ContentGoal.code).where(ContentGoal.status == "active")
            )
        ).all()
    }
    option_pools: dict[str, set[str]] = {}
    for pool_name in ("struct", "tone", "style"):
        row = await session.get(PoolOption, pool_name)
        if row is not None and row.status == ACTIVE and isinstance(row.options, list):
            option_pools[pool_name] = {str(v) for v in row.options}
        else:
            option_pools[pool_name] = set()

    refs: list[str] = []
    goals = payload.get("goals") or []
    if isinstance(goals, list):
        for item in goals:
            goal = item.get("goal") if isinstance(item, dict) else None
            if goal is None:
                continue
            if goal not in goal_codes:
                raise InvalidCandidatePayload(
                    f"goal {goal!r} not in ContentGoal active dictionary"
                )
            refs.append(f"goal:{goal}")
    structures = payload.get("structures") or []
    if isinstance(structures, list):
        for item in structures:
            structure = item.get("structure") if isinstance(item, dict) else None
            if structure is None:
                continue
            if structure not in option_pools.get("struct", set()):
                raise InvalidCandidatePayload(
                    f"structure {structure!r} not in struct pool options"
                )
            refs.append(f"structure:{structure}")
    tone = payload.get("tone")
    if tone is not None:
        if tone not in option_pools.get("tone", set()):
            raise InvalidCandidatePayload(f"tone {tone!r} not in tone pool options")
        refs.append(f"tone:{tone}")
    style = payload.get("style")
    if style is not None:
        if style not in option_pools.get("style", set()):
            raise InvalidCandidatePayload(f"style {style!r} not in style pool options")
        refs.append(f"style:{style}")
    goal = payload.get("goal")
    if goal is not None:
        if goal not in goal_codes:
            raise InvalidCandidatePayload(
                f"goal {goal!r} not in ContentGoal active dictionary"
            )
        refs.append(f"goal:{goal}")
    if not refs:
        raise InvalidCandidatePayload(
            "package_draft payload carries no in-dictionary goal/struct/tone/style value"
        )
    return refs


ADAPTERS: dict[str, CandidateAdapter] = {
    "pwc_combo": apply_pwc_combo,
    "field_plan": apply_field_plan,
    "c1_recognition": apply_c1_recognition,
    "atom_batch": apply_atom_batch,
    "c7_layer4": apply_c7_layer4,
    "package_draft": apply_package_draft,
}
