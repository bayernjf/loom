"""段12 content_products 状态机（Q56/Q59 实现补登；Q124 补 discarded 终态）。

状态：draft → generating → review → ready_for_publish / rejected / revising；
Q124/Q56-b 增加终态 discarded（运营作废骨架回池）。
- generate：draft|revising → generating（首次生成 / 改稿重生成）
- complete：generating → review（生成 + 复检完成）
- approve：review → ready_for_publish（客户通过）
- reject：review → rejected（客户驳回，Q59 必选原因）
- revise：review → revising（客户改稿，强制重过四项复检）
- manual_resubmit：revising → review（Q56-a/Q122 客户人工编辑正文后重过复检提交，
  不走 ARTICLE-GEN、不增 regenerate_count）
- discard：review|revising|rejected → discarded（Q56-b/Q124 运营作废骨架回池，
  必记难产原因；ready_for_publish 已进发布不可作废，generating/draft 不可作废）

重生成上限（Q56）：regenerate_count ≥ 3 时 revise 拒绝，只能 reject（转人工/作废回池）。
"""

from app.content.models import (
    CONTENT_DISCARDED,
    CONTENT_DRAFT,
    CONTENT_GENERATING,
    CONTENT_READY,
    CONTENT_REJECTED,
    CONTENT_REVIEW,
    CONTENT_REVISING,
    MAX_REGENERATE,
)

EVENT_GENERATE = "generate"
EVENT_COMPLETE = "complete"
EVENT_APPROVE = "approve"
EVENT_REJECT = "reject"
EVENT_REVISE = "revise"
EVENT_MANUAL_RESUBMIT = "manual_resubmit"
EVENT_DISCARD = "discard"

# event → 允许的前置状态（机械口径；原文未给完整迁移表，Q59 只给五态语义）。
_TRANSITIONS = {
    EVENT_GENERATE: {CONTENT_DRAFT, CONTENT_REVISING},
    EVENT_COMPLETE: {CONTENT_GENERATING},
    EVENT_APPROVE: {CONTENT_REVIEW},
    EVENT_REJECT: {CONTENT_REVIEW},
    EVENT_REVISE: {CONTENT_REVIEW},
    EVENT_MANUAL_RESUBMIT: {CONTENT_REVISING},
    EVENT_DISCARD: {CONTENT_REVIEW, CONTENT_REVISING, CONTENT_REJECTED},
}

_TARGET = {
    EVENT_GENERATE: CONTENT_GENERATING,
    EVENT_COMPLETE: CONTENT_REVIEW,
    EVENT_APPROVE: CONTENT_READY,
    EVENT_REJECT: CONTENT_REJECTED,
    EVENT_REVISE: CONTENT_REVISING,
    EVENT_MANUAL_RESUBMIT: CONTENT_REVIEW,
    EVENT_DISCARD: CONTENT_DISCARDED,
}


def allowed_events(status: str) -> list[str]:
    """给定状态可外放的事件（返回保持定义顺序）。"""
    return [e for e in _TRANSITIONS if status in _TRANSITIONS[e]]


def can_transition(status: str, event: str) -> bool:
    return status in _TRANSITIONS.get(event, set())


def target_status(status: str, event: str) -> str:
    """返回迁移后状态；事件对该状态不合法则抛 ValueError（调用方映射 409）。"""
    if not can_transition(status, event):
        raise ValueError(f"event {event!r} not allowed from status {status!r}")
    return _TARGET[event]


def revise_allowed(
    status: str, regenerate_count: int, limit: int = MAX_REGENERATE
) -> bool:
    """Q56：review 态且重生成次数未达上限才可改稿（超限只能 reject 转人工/作废回池）。

    limit 运行值取配置中心 content.regen_limit（Q56 运营可改，默认 3）；
    MAX_REGENERATE 常量为种子默认/兜底，调用方（service）传入 knob 值。
    """
    return status == CONTENT_REVIEW and regenerate_count < limit
