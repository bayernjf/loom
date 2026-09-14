"""段7/8 静态底表纯逻辑单测（Q34/Q36/Q40）。"""

from types import SimpleNamespace

from app.platform.platform_adaptation import pa_rules


def _weights(**kw):
    return kw


def test_validate_weights_17_ok_and_sum_boundary():
    assert pa_rules.validate_weights_17(_weights(goal=0.5, hook=0.5)) == []
    violations = pa_rules.validate_weights_17(_weights(goal=0.6, hook=0.5))
    assert "weight_sum_exceeds_1" in violations


def test_validate_weights_17_unknown_key_and_range():
    violations = pa_rules.validate_weights_17({"nope": 0.5, "goal": 1.5})
    assert "unknown_weight_keys:nope" in violations
    assert "weight_out_of_range:goal" in violations


def test_validate_fit_weights_requires_four_dims_sum_1():
    assert "missing_fit_dims:load" in pa_rules.validate_fit_weights(
        {"traffic": 0.4, "safe": 0.3, "conv": 0.3}
    )
    assert "weight_sum_not_1" in pa_rules.validate_fit_weights(
        {"traffic": 0.4, "safe": 0.2, "conv": 0.2, "load": 0.1}
    )
    assert pa_rules.validate_fit_weights(
        {"traffic": 0.4, "safe": 0.2, "conv": 0.2, "load": 0.2}
    ) == []


def test_compute_fit_score():
    slot = SimpleNamespace(traffic=80, safe=50, conv=40, load=100)
    weights = {"traffic": 0.4, "safe": 0.2, "conv": 0.2, "load": 0.2}
    assert pa_rules.compute_fit_score(slot, weights) == 32 + 10 + 8 + 20


def _rule(level, effect, platform="p", slot_type="st", slot_id=None, country=None):
    return SimpleNamespace(
        selector_level=level,
        platform=platform,
        slot_type=slot_type,
        slot_id=slot_id,
        country=country,
        effect=effect,
        status="active",
    )


def test_find_conflicts_same_level_condition_different_effect():
    old = _rule("platform", "blocked")
    candidate = _rule("platform", "partial")
    assert pa_rules.find_conflicts([old], candidate) == [old]
    # 同结论不算冲突；不同层级/条件不算冲突
    assert pa_rules.find_conflicts([old], _rule("platform", "blocked")) == []
    assert pa_rules.find_conflicts([old], _rule("slot", "partial", slot_id="s1")) == []
    assert pa_rules.find_conflicts([old], _rule("platform", "partial", country="US")) == []


def test_resolve_effect_level_priority_then_strictest():
    platform_block = _rule("platform", "blocked")
    slot_partial = _rule("slot", "partial", slot_id="s1")
    # slotId 层级高于 platform → partial 生效（高优先级覆盖）
    assert pa_rules.resolve_effect([platform_block, slot_partial]) == "partial"
    # 同级取最严
    assert pa_rules.resolve_effect([_rule("platform", "partial"), platform_block]) == "blocked"
    assert pa_rules.resolve_effect([]) is None


def test_validate_selector_required_fields():
    assert pa_rules.validate_selector("nope", None, None, None) == ["unknown_selector_level:nope"]
    assert "platform_required" in pa_rules.validate_selector("platform", None, None, None)
    assert "slot_type_required" in pa_rules.validate_selector("slot_type", None, None, None)
    assert "slot_id_required" in pa_rules.validate_selector("slot", "p", None, None)
    assert pa_rules.validate_selector("slot", "p", None, "s1") == []
