"""配置中心类型/校验纯逻辑单测（07 §7.4 通用校验器）。"""

import pytest

from app.core.config_center.config_rules import ConfigValidationError, coerce


def test_int_and_float_coercion():
    assert coerce(7, "int", {"min": 1, "max": 100}) == 7
    assert coerce(3, "float", None) == 3.0
    with pytest.raises(ConfigValidationError):
        coerce(1.5, "int", None)
    with pytest.raises(ConfigValidationError):
        coerce("7", "int", None)


def test_bool_must_be_explicit_boolean():
    assert coerce(True, "bool", None) is True
    with pytest.raises(ConfigValidationError):
        coerce(1, "bool", None)
    with pytest.raises(ConfigValidationError):
        coerce("true", "bool", None)


def test_string_and_json_passthrough():
    assert coerce("x", "string", None) == "x"
    with pytest.raises(ConfigValidationError):
        coerce("", "string", None)
    payload = {"a": [1, 2]}
    assert coerce(payload, "json", None) == payload


def test_numeric_bounds_and_choices():
    with pytest.raises(ConfigValidationError):
        coerce(0, "int", {"min": 1})
    with pytest.raises(ConfigValidationError):
        coerce(1.01, "float", {"min": 0.0, "max": 1.0})
    assert coerce(0.8, "float", {"min": 0.0, "max": 1.0}) == 0.8
    with pytest.raises(ConfigValidationError):
        coerce("ban", "string", {"choices": ["allow", "downgrade"]})
    assert coerce("allow", "string", {"choices": ["allow", "downgrade"]}) == "allow"


def test_bool_does_not_trigger_numeric_bounds():
    assert coerce(True, "bool", {"min": 0}) is True


def test_unknown_type_rejected():
    with pytest.raises(ConfigValidationError):
        coerce(1, "decimal", None)
