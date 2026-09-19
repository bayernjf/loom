"""Q126 段13 effect-callback 纯函数单测：metrics 归一与单条记录校验。

数据纪律（05 §1.1.1 硬性）：缺席指标不落、绝不当 0；计数为非负整数、
read_rate 为 0..1；captured_at 必须带时区；未知 metrics 键拒绝。
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.effects.schemas import EffectRecordIn
from app.core.effects.service import (
    EffectValidationError,
    normalize_metrics,
    validate_record,
)

# ---------- normalize_metrics ----------


def test_none_and_empty_metrics_become_none():
    assert normalize_metrics(0, None) is None
    assert normalize_metrics(0, {}) is None


def test_metrics_must_be_object():
    with pytest.raises(EffectValidationError) as exc:
        normalize_metrics(0, [1, 2])
    assert exc.value.field == "metrics"


def test_sparse_metrics_keep_only_provided_keys():
    out = normalize_metrics(0, {"plays": 10, "likes": 2, "read_rate": 0.5})
    assert out == {"plays": 10, "likes": 2, "read_rate": 0.5}
    # 缺席键不得补 0。
    assert "comments" not in out and "conversions" not in out


def test_explicit_null_value_is_dropped_not_zero():
    out = normalize_metrics(0, {"plays": None, "likes": 3})
    assert out == {"likes": 3}
    assert "plays" not in out


def test_unknown_metric_key_rejected():
    with pytest.raises(EffectValidationError) as exc:
        normalize_metrics(2, {"plays": 1, "followers": 9})
    assert exc.value.index == 2
    assert exc.value.field == "metrics.followers"


@pytest.mark.parametrize("bad", [-1, -100])
def test_counter_must_be_non_negative_integer(bad):
    with pytest.raises(EffectValidationError):
        normalize_metrics(0, {"plays": bad})


@pytest.mark.parametrize("bad", [True, False, 1.5, "9"])
def test_counter_rejects_bool_float_and_string(bad):
    with pytest.raises(EffectValidationError):
        normalize_metrics(0, {"plays": bad})


@pytest.mark.parametrize("good", [0, 1, 0.0, 0.5, 1.0])
def test_read_rate_accepts_numbers_in_range(good):
    assert normalize_metrics(0, {"read_rate": good})["read_rate"] == good


@pytest.mark.parametrize("bad", [-0.01, 1.01, True, "0.5"])
def test_read_rate_rejects_out_of_range_bool_string(bad):
    with pytest.raises(EffectValidationError):
        normalize_metrics(0, {"read_rate": bad})


# ---------- validate_record ----------


def test_validate_record_normalizes_captured_at_to_utc():
    ts = datetime(2026, 9, 1, 18, 0, tzinfo=timezone(timedelta(hours=8)))  # 18:00 +08
    rec = EffectRecordIn(
        content_id="c1", platform_post_id="p1", captured_at=ts, metrics=None
    )
    content_id, post_id, captured, metrics = validate_record(0, rec)
    assert content_id == "c1" and post_id == "p1" and metrics is None
    assert captured == datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize("field", ["content_id", "platform_post_id"])
def test_blank_required_string_rejected(field):
    payload = {"content_id": "c", "platform_post_id": "p", "captured_at": "2026-09-01T10:00:00Z"}
    payload[field] = "   "
    rec = EffectRecordIn(**payload)
    with pytest.raises(EffectValidationError) as exc:
        validate_record(3, rec)
    assert exc.value.field == field and exc.value.index == 3


def test_naive_captured_at_rejected():
    rec = EffectRecordIn(
        content_id="c1",
        platform_post_id="p1",
        captured_at=datetime(2026, 9, 1, 10, 0),  # noqa: DTZ001  # 故意构造 naive 测拒绝
    )
    with pytest.raises(EffectValidationError) as exc:
        validate_record(0, rec)
    assert exc.value.field == "captured_at"
