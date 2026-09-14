"""配置项类型与通用校验（07 §7.4：min/max/choices 通用校验器）。"""

TYPE_INT = "int"
TYPE_FLOAT = "float"
TYPE_BOOL = "bool"
TYPE_STRING = "string"
TYPE_JSON = "json"
VALUE_TYPES = frozenset({TYPE_INT, TYPE_FLOAT, TYPE_BOOL, TYPE_STRING, TYPE_JSON})


class ConfigValidationError(Exception):
    pass


def coerce(value, value_type: str, validation: dict | None = None):
    """把入参按声明类型解析并跑通用区间/枚举校验，返回落库值。

    bool 必须显式 true/false（不接受 "true"/1，避免静默歧义）；
    int 拒绝 1.5 这类带小数浮点；float 接受 int/float。
    """
    if value_type not in VALUE_TYPES:
        raise ConfigValidationError(f"unknown value_type {value_type!r}")

    if value_type == TYPE_BOOL:
        if not isinstance(value, bool):
            raise ConfigValidationError("expected boolean")
        coerced = value
    elif value_type == TYPE_INT:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigValidationError("expected integer")
        coerced = value
    elif value_type == TYPE_FLOAT:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigValidationError("expected number")
        coerced = float(value)
    elif value_type == TYPE_STRING:
        if not isinstance(value, str) or not value:
            raise ConfigValidationError("expected non-empty string")
        coerced = value
    else:
        coerced = value

    rules = validation or {}
    if "choices" in rules and coerced not in rules["choices"]:
        raise ConfigValidationError(f"value must be one of {rules['choices']}")
    if isinstance(coerced, (int, float)) and not isinstance(coerced, bool):
        if "min" in rules and coerced < rules["min"]:
            raise ConfigValidationError(f"value {coerced} < min {rules['min']}")
        if "max" in rules and coerced > rules["max"]:
            raise ConfigValidationError(f"value {coerced} > max {rules['max']}")
    return coerced
