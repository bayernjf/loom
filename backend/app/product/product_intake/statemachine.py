"""productIntake15 状态机（docs/13 §1.1，line 1454 + Q3/Q4/Q5）。

纯逻辑模块，不碰数据库；迁移表逐条对应 docs/13，未给出的事件不擅自新增。
终态（已入库/驳回/已归档）不接受任何事件；类目创建中只接受 B2 结果。
"""

from dataclasses import dataclass

DRAFT = "draft"
AI_RECOGNIZING = "ai_recognizing"
PENDING_CONFIRM = "pending_confirm"
PENDING_PARAMS = "pending_params"
PENDING_QUOTA = "pending_quota"
SUBMITTED = "submitted"
IN_REVIEW = "in_review"
NEED_MORE_INFO = "need_more_info"
APPROVED = "approved"
MODELING = "modeling"
STORED = "stored"
STORE_FAILED = "store_failed"
REJECTED = "rejected"
ARCHIVED = "archived"
CATEGORY_CREATING = "category_creating"

# 对外展示名（docs/05 §2.1 的 15 态顺序）。
STATE_LABELS = {
    DRAFT: "草稿",
    AI_RECOGNIZING: "AI识别中",
    PENDING_CONFIRM: "待确认",
    PENDING_PARAMS: "待补充参数",
    PENDING_QUOTA: "待确认额度",
    SUBMITTED: "已提交",
    IN_REVIEW: "审核中",
    NEED_MORE_INFO: "需补充资料",
    APPROVED: "已通过",
    MODELING: "建模中",
    STORED: "已入库",
    STORE_FAILED: "入库失败",
    REJECTED: "驳回",
    ARCHIVED: "已归档",
    CATEGORY_CREATING: "类目创建中",
}

TERMINAL_STATES = frozenset({STORED, REJECTED, ARCHIVED})

ROLE_OPERATIONS = "operations"


@dataclass(frozen=True)
class Transition:
    event: str
    target: str
    requires_role: str | None = None


# 当前态 → 允许的迁移。依据 docs/13 §1.1 逐行落；【待补】迁移未实现。
TRANSITIONS: dict[str, list[Transition]] = {
    DRAFT: [Transition("submit", AI_RECOGNIZING)],
    AI_RECOGNIZING: [
        Transition("wf01_confirm", PENDING_CONFIRM),
        Transition("wf01_missing_params", PENDING_PARAMS),
        Transition("wf01_quota", PENDING_QUOTA),
        Transition("wf01_cold_start", CATEGORY_CREATING),
    ],
    PENDING_CONFIRM: [
        Transition("ops_confirm", SUBMITTED, requires_role=ROLE_OPERATIONS),
        # Q1 direct_approve：高置信由系统自动确认过类目，不需运营（Q3 仅中置信出待办）。
        Transition("auto_confirm", SUBMITTED),
        Transition("to_cold_start", CATEGORY_CREATING, requires_role=ROLE_OPERATIONS),
    ],
    PENDING_PARAMS: [
        Transition("params_completed", SUBMITTED),
        Transition("reject", REJECTED, requires_role=ROLE_OPERATIONS),
    ],
    PENDING_QUOTA: [Transition("quota_confirmed", SUBMITTED)],
    SUBMITTED: [Transition("send_review", IN_REVIEW)],
    IN_REVIEW: [
        Transition("review_need_info", NEED_MORE_INFO),
        Transition("review_approve", APPROVED),
        Transition("review_reject", REJECTED),
    ],
    NEED_MORE_INFO: [Transition("resubmit", SUBMITTED)],
    APPROVED: [Transition("start_modeling", MODELING)],
    MODELING: [
        Transition("model_stored", STORED),
        Transition("model_failed", STORE_FAILED),
    ],
    STORE_FAILED: [
        Transition("failed_to_info", NEED_MORE_INFO),
        Transition("failed_reject", REJECTED),
    ],
    # 类目创建中只接受 B2 结果（Q5）；运营二选一均需 operations 角色（Q3）。
    CATEGORY_CREATING: [
        Transition("b2_approved", PENDING_PARAMS, requires_role=ROLE_OPERATIONS),
        Transition("b2_parent_fallback", PENDING_PARAMS, requires_role=ROLE_OPERATIONS),
        Transition("b2_rejected", NEED_MORE_INFO, requires_role=ROLE_OPERATIONS),
    ],
}


class IllegalTransition(Exception):
    """非法状态迁移：终态收到事件 / 当前态不存在该事件（docs/13 §1.1 建议拦截）。"""


class RoleRequired(Exception):
    """迁移要求特定角色（如类目确认必须运营，Q3）。"""


def allowed_events(status: str) -> list[str]:
    return [t.event for t in TRANSITIONS.get(status, [])]


def transition(status: str, event: str, actor_roles: list[str] | None = None) -> str:
    """返回迁移后的目标态；非法迁移抛 IllegalTransition，角色不满足抛 RoleRequired。"""
    if status in TERMINAL_STATES:
        raise IllegalTransition(f"{status} is terminal and accepts no events")

    for candidate in TRANSITIONS.get(status, []):
        if candidate.event == event:
            if candidate.requires_role and candidate.requires_role not in (
                actor_roles or []
            ):
                raise RoleRequired(f"event {event} requires role {candidate.requires_role}")
            return candidate.target

    raise IllegalTransition(f"event {event} is not valid in state {status}")


def missing_required_fields(profile: dict, required_fids: list[str]) -> list[str]:
    """D7.1 闸门1：18 通用字段缺字段阻断提交。空串/None 视为缺失。"""
    return [fid for fid in required_fids if not profile.get(fid)]
