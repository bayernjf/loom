"""候选 confirmed/modified 后的落库适配器（Q76-3）。

key = candidate.target_type；适配器只调用既有业务服务，不绕过任何
预筛/合规/评分/限量/Gate。已接入：pwc_combo（WF-04）、field_plan（WF-02，Q78）、
c1_recognition（WF-01，Q79）、atom_batch（WF-03，Q80）。
"""

from collections.abc import Awaitable, Callable

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
    body = BatchSubmitRequest(**data, source="ai", actor=actor)
    batch = await atom_service.submit_batch(
        session, candidate.product_space_id, body, actor
    )
    return [batch.batch_id]


ADAPTERS: dict[str, CandidateAdapter] = {
    "pwc_combo": apply_pwc_combo,
    "field_plan": apply_field_plan,
    "c1_recognition": apply_c1_recognition,
    "atom_batch": apply_atom_batch,
}
