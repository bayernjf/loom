"""段12 content_products 状态机纯逻辑（Q56/Q59 实现补登）。"""

import pytest

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
    # Q124：review 态同时外放运营作废（discard）。
    assert set(allowed_events(CONTENT_REVIEW)) == {
        "approve", "reject", "revise", "discard"
    }
    assert set(allowed_events(CONTENT_DRAFT)) == {"generate"}
    assert allowed_events(CONTENT_READY) == []
    # discarded 为终态，无外放事件。
    assert allowed_events(CONTENT_DISCARDED) == []


def test_discard_from_review_revising_rejected():
    # Q124/Q56-b：三种在制/驳回态可作废回池。
    assert target_status(CONTENT_REVIEW, "discard") == CONTENT_DISCARDED
    assert target_status(CONTENT_REVISING, "discard") == CONTENT_DISCARDED
    assert target_status(CONTENT_REJECTED, "discard") == CONTENT_DISCARDED


def test_discard_illegal_from_other_states():
    # draft/generating 无骨架或在制瞬态、ready 已进发布，均不可作废。
    for status in (CONTENT_DRAFT, CONTENT_GENERATING, CONTENT_READY, CONTENT_DISCARDED):
        assert can_transition(status, "discard") is False
        with pytest.raises(ValueError):
            target_status(status, "discard")


def test_revise_limited_by_regenerate_cap():
    assert revise_allowed(CONTENT_REVIEW, 0) is True
    assert revise_allowed(CONTENT_REVIEW, MAX_REGENERATE - 1) is True
    assert revise_allowed(CONTENT_REVIEW, MAX_REGENERATE) is False
    assert revise_allowed(CONTENT_DRAFT, 0) is False


def test_can_transition():
    assert can_transition(CONTENT_REVIEW, "approve") is True
    assert can_transition(CONTENT_DRAFT, "approve") is False
    assert can_transition(CONTENT_REVIEW, "unknown_event") is False
