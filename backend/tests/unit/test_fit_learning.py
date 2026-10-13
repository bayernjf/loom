"""fit_score 自学习候选分计算单测（Q325 起草，Q352 接线；02 C1.268 / C1.295）。

覆盖 docs/design-q324 §7 拍板映射：
- traffic ← plays、conv ← inquiries+conversions、load ← read_rate；
- safe 恒不在建议里（无效果指标可学，维持人工）；
- 源键缺席的维度不进取值（Q293：未采集不得显示成"学到 0 分"）；
- 数据不足（无 metrics / 代理指标全零）→ 返回 None，不触发自学习（Q293 口径）；
- 输出为 0-100 advisory 建议、置信度由互动辅助信号归一化。
门控本体在 `core/config.py`（进程 settings），不在本模块——见文件末两条用例。
"""

from app.core.config import Settings
from app.platform.platform_adaptation.fit_learning import propose_fit_from_metrics


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
    # 门控本体是进程 settings（LOOM_FIT_LEARNING_ENABLED），默认关。
    # 读字段默认值而非实例化 Settings——本地 .env 可能把它显式打开。
    assert Settings.model_fields["fit_learning_enabled"].default is False


def test_absent_source_key_is_not_scored_as_zero():
    # Q293 数据纪律：read_rate 未采集 ≠ 完读率为 0，load 维度直接不进取值。
    p = propose_fit_from_metrics({"plays": 50_000, "inquiries": 100, "conversions": 0})
    assert p is not None
    assert set(p.scores) == {"traffic", "conv"}
    assert "load" not in p.scores


def test_only_conversion_signal_learns_conv_alone():
    p = propose_fit_from_metrics({"conversions": 100, "read_rate": 0.25})
    assert p is not None
    assert set(p.scores) == {"conv", "load"}
    assert "traffic" not in p.scores
    # 无 plays 分母时置信度不可算，如实回 0（不是"零互动"，是"无从判断"）。
    assert p.confidence == 0.0
