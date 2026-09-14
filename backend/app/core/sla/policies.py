"""SLA 策略（Q49）：各待办类型的黄/红口径。

- escalated（红）一律以 due_at 为准——各类型创建待办时按自身 SLA 设 due（72h/48h/7d）。
- 黄色（看板预警）原文仅给法审"24h 黄/48h 升级"，故只对 law_review 定义黄色窗口；
  其余类型黄色口径【原文未给出，待补】，到期前一律 green。
"""

from datetime import UTC, timedelta

from app.core.config_center.cache import config_cache


def _as_utc(dt):
    # SQLite 不保留 tz（读回 naive）；统一按 UTC 解释。
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

YELLOW_BY_TYPE = {
    # Q49：法审 24h 黄 / 48h 升级。值可经配置中心热更（sla.yellow_hours，种子 24）。
    "law_review": lambda: timedelta(hours=config_cache.get_int("sla.yellow_hours", 24)),
}


def yellow_at(todo, now) -> object:
    """返回该待办的黄色起始时刻；该类型无黄色口径则 None。"""
    fn = YELLOW_BY_TYPE.get(todo.todo_type)
    if fn is None:
        return None
    return _as_utc(todo.created_at) + fn()


def sla_state(todo, now) -> str:
    """看板态：resolved / red（已升级或过 due）/ yellow / green。"""
    if todo.status in ("resolved",):
        return "resolved"
    if todo.status == "escalated" or _as_utc(todo.due_at) <= now:
        return "red"
    y = yellow_at(todo, now)
    if y is not None and now >= y:
        return "yellow"
    return "green"
