"""M12 驾驶舱聚合查询（Q92；纯只读，无新表/无迁移/不物化）。

口径（02 C1.36 接缝四拍板项）：
- Token 成本：默认近 30 天可传 from/to（半开区间 [from 00:00, to+1d 00:00)，
  UTC）；计费行 = status=succeeded 且 model_id 非空（合成模型价 0 同样计入调用数），
  按天×model_id×currency_code 聚合 runs/tokens/cost，另附 skill_id 汇总；
  failed 行不计费，按 skill_id 单列失败数；多币种分组不换算（币种原文【待补】）。
- 人工审核工作量：积压为当前快照（无时窗）——候选 pending_review 按 target_type
  计数+该类最老等待秒数；ops_todos 未决按 todo_type 拆 open(未到期)/overdue
  (open 且 due_at 已过)/escalated。窗口产出 = reviewed_at/resolved_at 落窗内计数。
  Q70 二期项（智能派单/10% 抽检/6 场景细分）不做。
"""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.skill7.models import SkillCandidate, SkillRun
from app.product.modeling.models import OpsTodo

WINDOW_DEFAULT_DAYS = 30


class DashboardWindowInvalid(ValueError):
    """时间窗非法（from 晚于 to）。"""


def default_window(today: date | None = None) -> tuple[date, date]:
    today = today or datetime.now(UTC).date()
    return today - timedelta(days=WINDOW_DEFAULT_DAYS - 1), today


def window_bounds(
    date_from: date | None, date_to: date | None
) -> tuple[datetime, datetime]:
    if date_from is None or date_to is None:
        d_from, d_to = default_window()
        date_from = date_from or d_from
        date_to = date_to or d_to
    if date_from > date_to:
        raise DashboardWindowInvalid("date_from must be on or before date_to")
    start = datetime.combine(date_from, time.min, tzinfo=UTC)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
    return start, end


async def token_cost_summary(
    session: AsyncSession, *, date_from: date | None, date_to: date | None
) -> dict:
    start, end = window_bounds(date_from, date_to)

    daily_rows = await session.execute(
        select(
            func.date(SkillRun.created_at).label("day"),
            SkillRun.model_id,
            SkillRun.currency_code,
            func.count().label("runs"),
            func.coalesce(func.sum(SkillRun.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(SkillRun.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(SkillRun.input_cost), 0).label("input_cost"),
            func.coalesce(func.sum(SkillRun.output_cost), 0).label("output_cost"),
        )
        .where(
            SkillRun.status == "succeeded",
            SkillRun.model_id.is_not(None),
            SkillRun.created_at >= start,
            SkillRun.created_at < end,
        )
        .group_by("day", SkillRun.model_id, SkillRun.currency_code)
        .order_by("day", SkillRun.model_id)
    )
    daily = [
        {
            "date": row.day,
            "model_id": row.model_id,
            "currency_code": row.currency_code,
            "runs": row.runs,
            "input_tokens": int(row.input_tokens),
            "output_tokens": int(row.output_tokens),
            "input_cost": float(row.input_cost),
            "output_cost": float(row.output_cost),
            "total_cost": float(row.input_cost + row.output_cost),
        }
        for row in daily_rows
    ]

    skill_rows = await session.execute(
        select(
            SkillRun.skill_id,
            SkillRun.currency_code,
            func.count().label("runs"),
            func.coalesce(func.sum(SkillRun.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(SkillRun.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(SkillRun.input_cost), 0).label("input_cost"),
            func.coalesce(func.sum(SkillRun.output_cost), 0).label("output_cost"),
        )
        .where(
            SkillRun.status == "succeeded",
            SkillRun.model_id.is_not(None),
            SkillRun.created_at >= start,
            SkillRun.created_at < end,
        )
        .group_by(SkillRun.skill_id, SkillRun.currency_code)
        .order_by(SkillRun.skill_id)
    )
    by_skill = [
        {
            "skill_id": row.skill_id,
            "currency_code": row.currency_code,
            "runs": row.runs,
            "input_tokens": int(row.input_tokens),
            "output_tokens": int(row.output_tokens),
            "total_cost": float(row.input_cost + row.output_cost),
        }
        for row in skill_rows
    ]

    failed_rows = await session.execute(
        select(SkillRun.skill_id, func.count().label("failed_runs"))
        .where(
            SkillRun.status == "failed",
            SkillRun.created_at >= start,
            SkillRun.created_at < end,
        )
        .group_by(SkillRun.skill_id)
        .order_by(SkillRun.skill_id)
    )
    failed_by_skill = [
        {"skill_id": row.skill_id, "failed_runs": row.failed_runs}
        for row in failed_rows
    ]

    return {
        "window": {"from": start.date().isoformat(), "to": (end.date() - timedelta(days=1)).isoformat()},
        "daily": daily,
        "by_skill": by_skill,
        "failed_by_skill": failed_by_skill,
        "totals": {
            "runs": sum(row["runs"] for row in daily),
            "input_tokens": sum(row["input_tokens"] for row in daily),
            "output_tokens": sum(row["output_tokens"] for row in daily),
            "failed_runs": sum(row["failed_runs"] for row in failed_by_skill),
        },
    }


async def review_workload(
    session: AsyncSession, *, date_from: date | None, date_to: date | None
) -> dict:
    start, end = window_bounds(date_from, date_to)
    now = datetime.now(UTC)

    candidate_rows = await session.execute(
        select(
            SkillCandidate.target_type,
            func.count().label("pending"),
            func.min(SkillCandidate.created_at).label("oldest_at"),
        )
        .where(SkillCandidate.state == "pending_review")
        .group_by(SkillCandidate.target_type)
        .order_by(SkillCandidate.target_type)
    )
    candidate_backlog = []
    for row in candidate_rows:
        oldest_at = row.oldest_at
        if oldest_at is not None and oldest_at.tzinfo is None:
            # SQLite 回读丢时区；PG 列存 aware UTC
            oldest_at = oldest_at.replace(tzinfo=UTC)
        candidate_backlog.append(
            {
                "target_type": row.target_type,
                "pending": row.pending,
                "oldest_wait_seconds": int((now - oldest_at).total_seconds())
                if oldest_at is not None
                else None,
            }
        )

    todo_rows = await session.execute(
        select(
            OpsTodo.todo_type,
            func.sum(
                case((OpsTodo.status == "open", 1), else_=0)
            ).label("open_total"),
            func.sum(
                case(
                    ((OpsTodo.status == "open") & (OpsTodo.due_at < now), 1),
                    else_=0,
                )
            ).label("overdue"),
            func.sum(
                case((OpsTodo.status == "escalated", 1), else_=0)
            ).label("escalated"),
        )
        .where(OpsTodo.status.in_(["open", "escalated"]))
        .group_by(OpsTodo.todo_type)
        .order_by(OpsTodo.todo_type)
    )
    todo_backlog = [
        {
            "todo_type": row.todo_type,
            "open": int(row.open_total or 0) - int(row.overdue or 0),
            "overdue": int(row.overdue or 0),
            "escalated": int(row.escalated or 0),
        }
        for row in todo_rows
    ]

    decided_rows = await session.execute(
        select(SkillCandidate.state, func.count().label("decided"))
        .where(
            SkillCandidate.reviewed_at.is_not(None),
            SkillCandidate.reviewed_at >= start,
            SkillCandidate.reviewed_at < end,
        )
        .group_by(SkillCandidate.state)
        .order_by(SkillCandidate.state)
    )
    candidates_decided = [
        {"state": row.state, "count": row.decided} for row in decided_rows
    ]

    resolved_rows = await session.execute(
        select(OpsTodo.todo_type, func.count().label("resolved"))
        .where(
            OpsTodo.status == "resolved",
            OpsTodo.resolved_at.is_not(None),
            OpsTodo.resolved_at >= start,
            OpsTodo.resolved_at < end,
        )
        .group_by(OpsTodo.todo_type)
        .order_by(OpsTodo.todo_type)
    )
    todos_resolved = [
        {"todo_type": row.todo_type, "count": row.resolved} for row in resolved_rows
    ]

    return {
        "window": {"from": start.date().isoformat(), "to": (end.date() - timedelta(days=1)).isoformat()},
        "snapshot_at": now.isoformat(),
        "backlog": {
            "candidates": candidate_backlog,
            "todos": todo_backlog,
            "totals": {
                "pending_candidates": sum(row["pending"] for row in candidate_backlog),
                "open_todos": sum(row["open"] for row in todo_backlog),
                "overdue_todos": sum(row["overdue"] for row in todo_backlog),
                "escalated_todos": sum(row["escalated"] for row in todo_backlog),
            },
        },
        "window_output": {
            "candidates_decided": candidates_decided,
            "todos_resolved": todos_resolved,
        },
    }
