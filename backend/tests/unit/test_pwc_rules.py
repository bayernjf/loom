"""段5 PWC 纯逻辑单测：Q22/Q22a/Q22b 评分、Q23 重合去重、Q24 冷却、Q25/Q71。"""

from datetime import UTC, datetime, timedelta

from app.core.config_center.knobs import knob
from app.product.condition import pwc_rules as r


def test_overlap_ratio_jaccard():
    a = frozenset({1, 2, 3})
    b = frozenset({2, 3, 4})
    assert r.overlap_ratio(a, b) == 2 / 4
    assert r.overlap_ratio(frozenset(), frozenset()) == 0.0


def test_max_overlap_empty_pool_is_zero():
    assert r.max_overlap(frozenset({1}), []) == 0.0


def test_max_overlap_picks_largest():
    combo = frozenset({1, 2})
    pool = [frozenset({3, 4}), frozenset({1, 2, 3})]
    assert r.max_overlap(combo, pool) == 2 / 3


def test_score_full_formula():
    # 空池多样性=1；合理性=0.8*0.5+0.6*0.5=0.7；score=(0.7*0.6+1*0.4)*1.0=0.82
    out = r.score_combo(logic=0.8, fit=0.6, max_pool_overlap=0.0)
    assert out.scored is True
    assert round(out.score, 6) == 0.82
    assert out.detail["reasonableness"] == 0.7
    assert out.detail["diversity"] == 1.0
    assert out.detail["category_multiplier"] == 1.0


def test_score_diversity_uses_overlap():
    # 多样性 = 1-0.5 = 0.5；合理性=1.0（两个 AI 分都 1.0）→ 0.6+0.2=0.8
    out = r.score_combo(logic=1.0, fit=1.0, max_pool_overlap=0.5)
    assert round(out.score, 6) == 0.8


def test_score_missing_ai_subscore_not_fabricated():
    out = r.score_combo(logic=None, fit=0.6, max_pool_overlap=0.0)
    assert out.scored is False
    assert out.score is None
    assert out.needs_manual_gate is True
    assert out.detail["logic"] == "—"
    assert out.detail["fit"] == 0.6


def test_dup_line_q23():
    assert r.is_duplicate(0.8) is True
    assert r.is_duplicate(0.79) is False


def test_should_cooldown_three_hits_in_seven_days():
    assert r.should_cooldown(3) is True
    assert r.should_cooldown(2) is False


def test_cooldown_over():
    now = datetime(2026, 9, 14, tzinfo=UTC)
    assert r.cooldown_over(now - timedelta(days=1), now) is True
    assert r.cooldown_over(now + timedelta(days=1), now) is False
    assert r.cooldown_over(None, now) is False


def test_goals_intersect():
    assert r.goals_intersect(["ENGAGEMENT"], None) is True
    assert r.goals_intersect(["ENGAGEMENT", "TRUST"], ["TRUST"]) is True
    assert r.goals_intersect(["ENGAGEMENT"], ["TRUST"]) is False


def test_all_platforms_used():
    assert r.all_platforms_used({"x", "y"}, ["x"]) is True
    assert r.all_platforms_used({"x"}, ["x", "y"]) is False
    # 目标平台未配置：不产生已用终态（实现补）
    assert r.all_platforms_used({"x"}, None) is False
    assert r.all_platforms_used({"x"}, []) is False


def test_pool_health_bands():
    assert r.pool_health(0) == "critical"
    assert r.pool_health(49) == "critical"
    assert r.pool_health(50) == "low"
    assert r.pool_health(99) == "healthy_below_target"
    assert r.pool_health(100) == "target"


def test_constants_traceability():
    # 拍板值单一事实源为配置中心种子（02 §C2）；缓存未引导时 knob() 回落种子默认。
    assert r.single_run_max() == 50
    assert r.default_capacity() == 100
    assert (r.reasonableness_weight(), r.diversity_weight()) == (0.6, 0.4)
    assert (knob("pwc.w_logic"), knob("pwc.w_fit")) == (0.5, 0.5)
    assert (r.cooldown_window_days(), r.cooldown_hits(), r.cooldown_duration_days()) == (7, 3, 14)
    assert len(r.CONTENT_GOALS) == 5
