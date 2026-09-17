"""段12 content_products 状态机纯逻辑（Q56/Q59 实现补登）。"""

import pytest

from app.content.models import (
    CONTENT_DRAFT,
    CONTENT_GENERATING,
    CONTENT_READY,
    CONTENT_REJECTED,
    CONTENT_REVIEW,
    CONTENT_REVISING,
    MAX_REGENERATE,
)
from app.content.statemachine import (
    allowed_events,
    can_transition,
    revise_allowed,
    target_status,
)


def test_happy_path_draft_to_ready():
    assert target_status(CONTENT_DRAFT, "generate") == CONTENT_GENERATING
    assert target_status(CONTENT_GENERATING, "complete") == CONTENT_REVIEW
    assert target_status(CONTENT_REVIEW, "approve") == CONTENT_READY


def test_reject_and_revise():
    assert target_status(CONTENT_REVIEW, "reject") == CONTENT_REJECTED
    assert target_status(CONTENT_REVIEW, "revise") == CONTENT_REVISING
    assert target_status(CONTENT_REVISING, "generate") == CONTENT_GENERATING


def test_illegal_transition_raises():
    with pytest.raises(ValueError):
        target_status(CONTENT_DRAFT, "approve")
    with pytest.raises(ValueError):
        target_status(CONTENT_GENERATING, "revise")
    with pytest.raises(ValueError):
        target_status(CONTENT_READY, "reject")


def test_allowed_events_expose_customer_actions():
    assert set(allowed_events(CONTENT_REVIEW)) == {"approve", "reject", "revise"}
    assert set(allowed_events(CONTENT_DRAFT)) == {"generate"}
    assert allowed_events(CONTENT_READY) == []


def test_revise_limited_by_regenerate_cap():
    assert revise_allowed(CONTENT_REVIEW, 0) is True
    assert revise_allowed(CONTENT_REVIEW, MAX_REGENERATE - 1) is True
    assert revise_allowed(CONTENT_REVIEW, MAX_REGENERATE) is False
    assert revise_allowed(CONTENT_DRAFT, 0) is False


def test_can_transition():
    assert can_transition(CONTENT_REVIEW, "approve") is True
    assert can_transition(CONTENT_DRAFT, "approve") is False
    assert can_transition(CONTENT_REVIEW, "unknown_event") is False
