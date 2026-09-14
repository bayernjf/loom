"""候选 confirmed/modified 后的落库适配器（Q76-3）。

key = candidate.target_type；适配器只调用既有业务服务，不绕过任何
预筛/合规/评分/限量/Gate。试点仅 pwc_combo（WF-04）。
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


CandidateAdapter = Callable[[AsyncSession, SkillCandidate, Actor], Awaitable[list[str]]]

ADAPTERS: dict[str, CandidateAdapter] = {
    "pwc_combo": apply_pwc_combo,
}
