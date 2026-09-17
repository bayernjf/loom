"""SLA 策略（Q49/Q114）：各待办类型的黄/红口径。

- escalated（红）一律以 due_at 为准——各类型创建待办时按自身 SLA 设 due（72h/48h/7d）。
- 黄色（看板预警）= 到期前 sla.yellow_hours 小时（种子 24）：
  - 法审（Q49 原文 24h 黄 / 48h 升级）与五型审核待办（Q70②）共用"到期前 24h"口径；
  - 五型黄色小时数原文未给，Q114 拍板 V1 统一"到期前 24h"作配置化占位，业务方给数后热更；
  - 其余类型黄色口径【原文未给出，待补】，到期前一律 green。
"""

from datetime import UTC, timedelta

from app.core.config_center.knobs import knob


def _as_utc(dt):
    # SQLite 不保留 tz（读回 naive）；统一按 UTC 解释。
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

# 有黄色窗口的待办类型；黄 = due_at - sla.yellow_hours（到期前 24h，配置中心可热更）。
YELLOW_TYPES = frozenset(
    {
        # Q49：法审 24h 黄 / 48h 升级。
        "law_review",
        # Q70② 五型审核待办（review_{target_type}）；Q114 V1 统一到期前 24h 占位。
        "review_pwc_combo",
        "review_field_plan",
        "review_c1_recognition",
        "review_atom_batch",
        "review_c7_layer4",
    }
)


def yellow_at(todo, now) -> object:
    """返回该待办的黄色起始时刻（due_at 前 yellow_hours）；无黄色口径则 None。"""
    if todo.todo_type not in YELLOW_TYPES:
        return None
    return _as_utc(todo.due_at) - timedelta(hours=knob("sla.yellow_hours"))


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
