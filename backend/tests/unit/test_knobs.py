"""M10c：knob() 消费侧——种子回落与缓存热更驱动纯规则结果。"""

import pytest

from app.core.config_center.cache import config_cache
from app.core.config_center.knobs import knob
from app.product.condition import pwc_rules


@pytest.fixture(autouse=True)
def _reset_cache():
    config_cache.invalidate()
    yield
    config_cache.invalidate()


def test_knob_falls_back_to_seed_default_when_cache_unloaded():
    assert config_cache.loaded is False
    assert knob("pwc.pool_target") == 100
    assert knob("c1.cold_start_floor") == 0.6
    assert knob("atom.evidence_timeout_days") == 7
    assert knob("ccr.law_review_due_hours") == 48


def test_hot_swapped_value_changes_rule_outcome():
    # 种子默认：3 次才冷却（Q24）。
    assert pwc_rules.should_cooldown(2) is False
    config_cache.apply({"pwc.cooldown_hits": 1})
    assert pwc_rules.should_cooldown(2) is True
    assert pwc_rules.should_cooldown(1) is True


def test_hot_swapped_pool_thresholds_change_health_band():
    # 70 个待用：默认档位 low（50 <= 70 < 70 为假，70 >= min70 → healthy_below_target）。
    assert pwc_rules.pool_health(70) == "healthy_below_target"
    config_cache.apply({"pwc.pool_min": 80, "pwc.pool_critical": 60})
    assert pwc_rules.pool_health(70) == "low"
