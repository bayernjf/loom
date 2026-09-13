import pytest

from app.product.product_intake import statemachine as sm


def test_happy_path_draft_to_stored():
    status = sm.DRAFT
    for event in [
        "submit",
        "wf01_confirm",
        "ops_confirm",
        "send_review",
        "review_approve",
        "start_modeling",
        "model_stored",
    ]:
        status = sm.transition(status, event, actor_roles=["operations"])
    assert status == sm.STORED


def test_terminal_states_reject_all_events():
    for terminal in sm.TERMINAL_STATES:
        with pytest.raises(sm.IllegalTransition):
            sm.transition(terminal, "submit")


def test_unknown_event_rejected():
    with pytest.raises(sm.IllegalTransition):
        sm.transition(sm.DRAFT, "approve_everything")


def test_category_confirm_requires_operations_role():
    with pytest.raises(sm.RoleRequired):
        sm.transition(sm.PENDING_CONFIRM, "ops_confirm", actor_roles=["customer"])
    assert (
        sm.transition(sm.PENDING_CONFIRM, "ops_confirm", actor_roles=["operations"])
        == sm.SUBMITTED
    )


def test_category_creating_only_accepts_b2_results():
    allowed = sm.allowed_events(sm.CATEGORY_CREATING)
    assert allowed == ["b2_approved", "b2_parent_fallback", "b2_rejected"]
    with pytest.raises(sm.IllegalTransition):
        sm.transition(sm.CATEGORY_CREATING, "ops_confirm", ["operations"])


def test_high_confidence_auto_confirm_needs_no_role():
    # Q1 direct_approve / Q3：仅中置信出运营待办，高置信系统自动确认。
    assert sm.transition(sm.PENDING_CONFIRM, "auto_confirm") == sm.SUBMITTED


def test_b2_branches():
    assert (
        sm.transition(sm.CATEGORY_CREATING, "b2_approved", ["operations"])
        == sm.PENDING_PARAMS
    )
    assert (
        sm.transition(sm.CATEGORY_CREATING, "b2_parent_fallback", ["operations"])
        == sm.PENDING_PARAMS
    )
    assert (
        sm.transition(sm.CATEGORY_CREATING, "b2_rejected", ["operations"])
        == sm.NEED_MORE_INFO
    )


def test_all_14_non_archived_states_reachable_or_defined():
    assert len(sm.STATE_LABELS) == 15
    assert set(sm.STATE_LABELS) == {
        sm.DRAFT,
        sm.AI_RECOGNIZING,
        sm.PENDING_CONFIRM,
        sm.PENDING_PARAMS,
        sm.PENDING_QUOTA,
        sm.SUBMITTED,
        sm.IN_REVIEW,
        sm.NEED_MORE_INFO,
        sm.APPROVED,
        sm.MODELING,
        sm.STORED,
        sm.STORE_FAILED,
        sm.REJECTED,
        sm.ARCHIVED,
        sm.CATEGORY_CREATING,
    }


def test_missing_required_fields_gate():
    required = ["f_name", "f_brief"]
    assert sm.missing_required_fields({"f_name": "x"}, required) == ["f_brief"]
    assert sm.missing_required_fields({"f_name": "x", "f_brief": ""}, required) == [
        "f_brief"
    ]
    assert sm.missing_required_fields({"f_name": "x", "f_brief": "y"}, required) == []
