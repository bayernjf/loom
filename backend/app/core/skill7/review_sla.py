"""Q70② 候选审核 SLA 待办挂接（Q94/C1.38）。

投递即按候选 target_type 的配置时限建一条 ops_todo（与候选同事务）；
裁决（applied/archived，含工作台批量路径）即 resolve。只对挂接后的新
投递生效——挂接前存量候选不回填（Q94 接缝④）。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_center.knobs import knob
from app.core.skill7 import registry
from app.core.skill7.models import SkillCandidate
from app.product.modeling.models import OpsTodo

REVIEW_TARGET_TYPES = (
    "pwc_combo",
    "field_plan",
    "c1_recognition",
    "atom_batch",
    "c7_layer4",
)

SLA_KEY = {tt: f"review.sla_hours.{tt}" for tt in REVIEW_TARGET_TYPES}
TODO_TYPE = {tt: f"review_{tt}" for tt in REVIEW_TARGET_TYPES}
ESCALATION_ACTION = "skill7.review_sla_escalated"


async def create_review_todos(
    session: AsyncSession, candidates: list[SkillCandidate]
) -> None:
    """每个候选一条 open 待办；assignee 取该 WF 的 skill7 Gate 角色。"""
    now = datetime.now(UTC)
    for cand in candidates:
        hours = knob(SLA_KEY[cand.target_type])
        session.add(
            OpsTodo(
                tenant_id=cand.tenant_id,
                todo_type=TODO_TYPE[cand.target_type],
                entity_type="skill_candidate",
                entity_id=cand.candidate_id,
                assignee_role=registry.review_role(cand.wf_id),
                detail={
                    "wf_id": cand.wf_id,
                    "target_type": cand.target_type,
                    "run_id": cand.run_id,
                    "candidate_index": cand.candidate_index,
                },
                due_at=now + timedelta(hours=float(hours)),
            )
        )


async def resolve_review_todo(
    session: AsyncSession, cand: SkillCandidate, resolution: str
) -> OpsTodo | None:
    """裁决即 resolve；open/escalated 均收口（升级不阻断裁决）。

    挂接前存量候选没有对应待办——查无则静默（Q94 接缝④不回填）。
    """
    todo = (
        await session.scalars(
            select(OpsTodo)
            .where(
                OpsTodo.entity_type == "skill_candidate",
                OpsTodo.entity_id == cand.candidate_id,
                OpsTodo.status.in_(("open", "escalated")),
            )
            .limit(1)
        )
    ).first()
    if todo is None:
        return None
    todo.status = "resolved"
    todo.resolved_at = datetime.now(UTC)
    todo.resolution = resolution
    return todo
