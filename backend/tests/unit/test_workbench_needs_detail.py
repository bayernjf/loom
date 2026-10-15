"""Q47 三包必审线：needs_detail 复用 Q9 fieldpool.needs_detail_conf 的纯规则。"""

import pytest

from app.core.config_center.cache import config_cache
from app.core.workbench.service import needs_detail


@pytest.fixture(autouse=True)
def _reset_cache():
    config_cache.invalidate()
    yield
    config_cache.invalidate()


def test_any_confidence_below_line_marks_needs_detail():
    # WF-07 内容目标规划 payload（0.92 / 0.85 / 0.78）：0.78 < 0.85 → 需细看。
    payload = {
        "goals": [
            {"goal": "种草", "confidence": 0.92},
            {"goal": "转化", "confidence": 0.85},
            {"goal": "复购", "confidence": 0.78},
        ]
    }
    assert needs_detail("package_draft", payload) is True


def test_all_confidences_at_or_above_line_not_marked():
    payload = {
        "structures": [
            {"structure": "痛点-方案", "confidence": 0.9, "partial": False},
            {"structure": "清单", "confidence": 0.85, "partial": True},
        ]
    }
    assert needs_detail("package_draft", payload) is False


def test_boundary_equal_to_line_not_marked():
    # 边界对齐 fieldpool `<` 语义：恰好等于线不标。
    assert needs_detail("package_draft", {"confidence": 0.85}) is False


def test_payload_without_confidence_not_marked():
    # 语气/风格 Skill 输出无 confidence：不编造、不标。
    assert needs_detail("package_draft", {"tone": "亲切", "style": "口语化"}) is False


def test_non_package_draft_target_never_marked():
    assert needs_detail("c1_recognition", {"confidence": 0.1}) is False


def test_nested_confidence_collected_recursively():
    payload = {"goal": "种草", "confirmed": False, "confidence": 0.5}
    assert needs_detail("package_draft", payload) is True
    assert needs_detail("package_draft", {"a": {"b": [{"confidence": 0.1}]}}) is True


def test_invalid_payload_shape_not_marked():
    assert needs_detail("package_draft", None) is False
    assert needs_detail("package_draft", {"confidence": "high"}) is False
    assert needs_detail("package_draft", {"confidence": True}) is False


def test_hot_swapped_line_changes_outcome():
    payload = {"goals": [{"goal": "种草", "confidence": 0.78}]}
    assert needs_detail("package_draft", payload) is True
    config_cache.apply({"fieldpool.needs_detail_conf": 0.5})
    assert needs_detail("package_draft", payload) is False
