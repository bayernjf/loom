"""SLA 看板策略纯逻辑（Q49：法审 24h 黄 / 48h 红）。"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.core.sla.policies import sla_state


def _todo(todo_type, created, due, status="open"):
    return SimpleNamespace(
        todo_type=todo_type, created_at=created, due_at=due, status=status, escalated_at=None
    )


def test_law_review_green_yellow_red():
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)
    created = now - timedelta(hours=20)
    assert sla_state(_todo("law_review", created, now + timedelta(hours=28)), now) == "green"
    created = now - timedelta(hours=30)
    assert sla_state(_todo("law_review", created, now + timedelta(hours=18)), now) == "yellow"
    assert sla_state(_todo("law_review", created, now - timedelta(hours=1)), now) == "red"
    escalated = _todo("law_review", created, now - timedelta(hours=1), status="escalated")
    escalated.escalated_at = now - timedelta(hours=1)
    assert sla_state(escalated, now) == "red"


def test_other_types_have_no_yellow_window():
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)
    # pws_ready 7 天 SLA：到期前始终 green（黄色口径原文未给）。
    created = now - timedelta(days=6)
    assert sla_state(_todo("pws_ready", created, now + timedelta(days=1)), now) == "green"
    assert sla_state(_todo("pws_ready", created, now - timedelta(hours=1)), now) == "red"


def test_review_types_have_yellow_window():
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)
    for tt in (
        "review_pwc_combo",
        "review_field_plan",
        "review_c1_recognition",
        "review_atom_batch",
        "review_c7_layer4",
    ):
        # 72h due：黄 = 到期前 24h（Q114 统一占位）——created+47h 尚未进入，created+49h 已进入。
        assert sla_state(_todo(tt, now - timedelta(hours=47), now + timedelta(hours=25)), now) == "green"
        assert sla_state(_todo(tt, now - timedelta(hours=49), now + timedelta(hours=23)), now) == "yellow"


def test_resolved_state():
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)
    todo = _todo("law_review", now, now + timedelta(hours=48), status="resolved")
    assert sla_state(todo, now) == "resolved"
