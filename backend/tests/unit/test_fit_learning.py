"""fit_score 自学习候选分计算单测（Q325，02 C1.268）。

覆盖 docs/design-q324 §7 拍板映射：
- traffic ← plays、conv ← inquiries+conversions、load ← read_rate；
- safe 恒不在建议里（无效果指标可学，维持人工）；
- 数据不足（无 metrics / 代理指标全零）→ 返回 None，不触发自学习（Q293 口径）；
- 输出为 0-100 advisory 建议、置信度由互动辅助信号归一化。
"""

from app.platform.platform_adaptation.fit_learning import (
    FIT_LEARNING_ENABLED,
    propose_fit_from_metrics,
)


def test_returns_none_when_no_metrics():
    assert propose_fit_from_metrics(None) is None
    assert propose_fit_from_metrics({}) is None


def test_returns_none_when_proxy_metrics_all_zero():
    # Q293：数据源缺失不按零值处理，代理指标为零即"无数据可学"。
    assert (
        propose_fit_from_metrics(
            {"plays": 0, "inquiries": 0, "conversions": 0, "read_rate": 0.0}
        )
        is None
    )


def test_mapping_traffic_conv_load():
    p = propose_fit_from_metrics(
        {
            "plays": 50_000,
            "likes": 1_000,
            "comments": 500,
            "shares": 250,
            "inquiries": 300,
            "conversions": 200,
            "read_rate": 0.6,
        }
    )
    assert p is not None
    # traffic = 50000/100000*100 = 50.0；conv = (300+200)/1000*100 = 50.0；load = 0.6*100 = 60.0
    assert p.scores["traffic"] == 50.0
    assert p.scores["conv"] == 50.0
    assert p.scores["load"] == 60.0
    # safe 恒不在建议里：四维只出三维。
    assert "safe" not in p.scores
    assert set(p.scores) == {"traffic", "conv", "load"}
    # 置信度 = (1000+500+250)/50000 = 0.035
    assert p.confidence == 0.035


def test_scores_clamped_to_100():
    p = propose_fit_from_metrics(
        {
            "plays": 1_000_000,
            "inquiries": 5_000,
            "conversions": 5_000,
            "read_rate": 1.2,  # 超 1 的比率也截断到 100
        }
    )
    assert p is not None
    assert p.scores["traffic"] == 100.0
    assert p.scores["conv"] == 100.0
    assert p.scores["load"] == 100.0


def test_gate_env_default_off():
    # 门控默认关：FIT_LEARNING_ENABLED 只在显式开启后才为 True。
    assert FIT_LEARNING_ENABLED is False
