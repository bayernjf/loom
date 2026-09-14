"""候选 confirmed/modified 后的落库适配器（Q76-3）。

key = candidate.target_type；适配器只调用既有业务服务，不绕过任何
预筛/合规/评分/限量/Gate。已接入：pwc_combo（WF-04）、field_plan（WF-02，Q78）。
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

ADAPTERS: dict[str, CandidateAdapter] = {
    "pwc_combo": apply_pwc_combo,
    "field_plan": apply_field_plan,
}
