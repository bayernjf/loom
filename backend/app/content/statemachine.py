"""段12 content_products 状态机（Q56/Q59 实现补登）。

状态：draft → generating → review → ready_for_publish / rejected / revising
- generate：draft|revising → generating（首次生成 / 改稿重生成）
- complete：generating → review（生成 + 复检完成）
- approve：review → ready_for_publish（客户通过）
- reject：review → rejected（客户驳回，Q59 必选原因）
- revise：review → revising（客户改稿，强制重过四项复检）

重生成上限（Q56）：regenerate_count ≥ 3 时 revise 拒绝，只能 reject（转人工/作废回池）。
"""

from app.content.models import (
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

# event → 允许的前置状态（机械口径；原文未给完整迁移表，Q59 只给五态语义）。
_TRANSITIONS = {
    EVENT_GENERATE: {CONTENT_DRAFT, CONTENT_REVISING},
    EVENT_COMPLETE: {CONTENT_GENERATING},
    EVENT_APPROVE: {CONTENT_REVIEW},
    EVENT_REJECT: {CONTENT_REVIEW},
    EVENT_REVISE: {CONTENT_REVIEW},
}

_TARGET = {
    EVENT_GENERATE: CONTENT_GENERATING,
    EVENT_COMPLETE: CONTENT_REVIEW,
    EVENT_APPROVE: CONTENT_READY,
    EVENT_REJECT: CONTENT_REJECTED,
    EVENT_REVISE: CONTENT_REVISING,
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


def revise_allowed(status: str, regenerate_count: int) -> bool:
    """Q56：review 态且重生成次数未达上限才可改稿（超限只能 reject 转人工/作废回池）。"""
    return status == CONTENT_REVIEW and regenerate_count < MAX_REGENERATE
