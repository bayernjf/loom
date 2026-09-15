"""通用 SLA 引擎（Q49/Q70）：开放待办到期升级，动作按类型留痕。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.skill7.review_sla import ESCALATION_ACTION as REVIEW_ESCALATION_ACTION
from app.core.skill7.review_sla import TODO_TYPE as REVIEW_TODO_TYPES
from app.product.modeling.models import OpsTodo

# 各待办类型的升级审计动作（ops_assist 沿用 M2 既有口径，保护既有契约/测试）。
ESCALATION_ACTIONS = {
    "ops_assist": "c1.todo_escalated",
    "pws_ready": "pws.ready_todo_escalated",
    "law_review": "law_review.escalated",
    "wordlist_rescan": "wordlist.rescan_todo_escalated",
    # Q70②/Q94：五型审核待办共用一个升级动作，target_type 在 todo.detail 可溯。
    **{todo_type: REVIEW_ESCALATION_ACTION for todo_type in REVIEW_TODO_TYPES.values()},
}
DEFAULT_ESCALATION_ACTION = "sla.todo_escalated"


async def escalate_due_todos(session: AsyncSession, now: datetime | None = None) -> list[OpsTodo]:
    """所有 open 待办过 due_at → escalated（幂等：escalated 不重复处理）。

    不提交事务——由调用方（既有模块包装/统一 runner）决定提交边界。
    """
    now = now or datetime.now(UTC)
    due = (
        await session.scalars(select(OpsTodo).where(OpsTodo.status == "open", OpsTodo.due_at <= now))
    ).all()
    for todo in due:
        todo.status = "escalated"
        todo.escalated_at = now
        await append_audit(
            session,
            tenant_id=todo.tenant_id,
            actor_id=None,
            actor_roles=None,
            action=ESCALATION_ACTIONS.get(todo.todo_type, DEFAULT_ESCALATION_ACTION),
            entity_type="ops_todo",
            entity_id=todo.todo_id,
            detail={"todo_type": todo.todo_type},
        )
    return list(due)
