"""fit_score 自学习候选分计算（Q325 起草，Q352 接线；02 C1.268 / 本次 C1.295）。

现状：`fit_score` 四维（traffic/safe/conv/load，`pa_rules.FIT_DIMS`）全为人工评估
（score_source=manual_eval，Q35），缺"被学的量"。唯一候选数据源是
`effect_records.metrics` 七键（play 数/like 数/comment 数/share 数/inquiry 数/conversion 数
＋read_rate 比率，`app.core.effects.models`）。

Q325 拍板映射（草案，业务语义需校准）：
- traffic ← plays（播放量为流量代理）
- conv    ← inquiries + conversions（询盘+转化为转化代理）
- load    ← read_rate（完读率为内容承载度代理）
- safe    ← **无效果指标可学，维持人工评估**（不臆造映射）

本模块只做"聚合 → 候选分建议"的**纯函数计算**，不碰 DB、不读门控：
- 输出是 advisory 建议（0-100 区间），不直接改写 `PublishSlot` 静态分；
- 稀疏口径：metrics 缺席的键＝未采集，对应维度**不进取值**（Q293 数据源缺失不按
  零值处理，也不得把"没采到"显示成"学到 0 分"）；
- 数据不足（无 metrics / 代理指标全零）时返回 None，调用方维持人工分。

消费方（唯一）＝`platform_adaptation/service.py:_fit_learning`，由进程门控
`LOOM_FIT_LEARNING_ENABLED`（`core/config.py`，默认关）决定是否把建议附到
`GET /api/admin/publish-slots/{id}/fit-score` 的 `learning` 键上；观察窗是配置中心
`platform.fit_learning_window_days`。开启也只是**摆给人看**，不写回静态分、不建候选、
不进 Gate（Q293：真自学习还欠业务四份规则，本件是 advisory 不是裁决）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

# 0-100 静态分区间（与 PublishSlot 四维静态分同一量纲，Q35）。
_SCORE_MAX = 100.0
# 归一化参考基准【实现补：工程草案值，业务可校准】——把聚合量映射到 0-100 时
# 使用的"100 分参考值"：plays 参考播放量、conv 参考询盘+转化量、load 为比率本身。
_REF_PLAYS = 100_000.0
_REF_CONV = 1_000.0


@dataclass(frozen=True)
class FitLearningProposal:
    """自学习候选分建议（只读，advisory）。

    `scores` 只含**有数据源**的可学维度（traffic/conv/load 的子集）；缺席源键对应
    维度不进取值，`safe` 恒不在建议里——安全维度无效果指标可学，维持人工评估。
    """

    scores: dict[str, float]
    confidence: float  # 0..1，likes/comments/shares 互动量归一化（辅助信号，不参与主分）
    sample_size: int = 0
    note: str = field(default="")


def _normalize(value: float, ref: float) -> float:
    """把聚合量压到 0-100 静态分区间（草案：value/ref 截断）。"""
    if ref <= 0:
        return 0.0
    return min(_SCORE_MAX, round(value / ref * _SCORE_MAX, 1))


def _seen_number(metrics: Mapping[str, float], key: str) -> float | None:
    """键缺席＝未采集，返回 None（不得当 0 参与评分）。"""
    value = metrics.get(key)
    if value is None:
        return None
    return float(value)


def propose_fit_from_metrics(
    metrics: Mapping[str, float] | None,
    *,
    sample_size: int = 0,
) -> FitLearningProposal | None:
    """由 effect metrics 聚合值计算候选分建议。

    返回 None 表示"数据不足，不触发自学习、维持人工分"（Q293 口径）。
    判据：无 metrics、或代理指标为零（plays≤0 且 inquiries+conversions≤0）。
    `safe` 恒不在建议里——安全维度无效果指标可学，维持人工评估。
    """
    if not metrics:
        return None
    plays = _seen_number(metrics, "plays") or 0.0
    inquiries = _seen_number(metrics, "inquiries") or 0.0
    conversions = _seen_number(metrics, "conversions") or 0.0
    read_rate = _seen_number(metrics, "read_rate")

    if plays <= 0 and inquiries + conversions <= 0:
        return None

    scores: dict[str, float] = {}
    if "plays" in metrics:
        scores["traffic"] = _normalize(plays, _REF_PLAYS)
    if "inquiries" in metrics or "conversions" in metrics:
        scores["conv"] = _normalize(inquiries + conversions, _REF_CONV)
    if read_rate is not None:
        scores["load"] = round(min(_SCORE_MAX, read_rate * _SCORE_MAX), 1)

    # 辅助信号：likes/comments/shares 互动量做置信度（0..1，不做主分）。
    engagement = sum((_seen_number(metrics, key) or 0.0) for key in ("likes", "comments", "shares"))
    confidence = 0.0 if plays <= 0 else round(min(1.0, engagement / plays), 3)

    note = "advisory 自学习建议：traffic/conv/load 由效果指标映射；safe 维持人工（无指标可学）"
    return FitLearningProposal(
        scores=scores,
        confidence=confidence,
        sample_size=sample_size,
        note=note,
    )


__all__ = [
    "FitLearningProposal",
    "propose_fit_from_metrics",
]
