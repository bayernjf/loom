"""fit_score 自学习候选分计算（Q325，02 C1.268，docs/design-q324 §7 按推荐落地）。

现状：`fit_score` 四维（traffic/safe/conv/load，`pa_rules.FIT_DIMS`）全为人工评估
（score_source=manual_eval，Q35），缺"被学的量"。唯一候选数据源是
`effect_records.metrics` 七键（play 数/like 数/comment 数/share 数/inquiry 数/conversion 数
＋read_rate 比率，`app.core.effects.models`）。

Q325 拍板映射（草案，业务语义需校准）：
- traffic ← plays（播放量为流量代理）
- conv    ← inquiries + conversions（询盘+转化为转化代理）
- load    ← read_rate（完读率为内容承载度代理）
- safe    ← **无效果指标可学，维持人工评估**（不臆造映射）

本模块只做"聚合 → 候选分建议"的**纯函数计算**：
- 输出是 advisory 建议（0-100 区间），不直接改写 `PublishSlot` 静态分；
- `LOOM_FIT_LEARNING_ENABLED`（默认关）门控"是否允许消费本模块产出"；
- 数据不足（无 effect 行 / 代理指标为零）时不触发、维持人工分（Q293 已定：
  数据源缺失不按零值处理），调用方拿 None 即走人工。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

# 是否允许消费自学习候选分（advisory 门控，默认关；开启后才把建议暴露给上游）。
FIT_LEARNING_ENABLED = os.getenv("LOOM_FIT_LEARNING_ENABLED", "0") == "1"

# 0-100 静态分区间（与 PublishSlot 四维静态分同一量纲，Q35）。
_SCORE_MAX = 100.0
# 归一化参考基准【实现补：工程草案值，业务可校准】——把聚合量映射到 0-100 时
# 使用的"100 分参考值"：plays 参考播放量、conv 参考询盘+转化量、load 为比率本身。
_REF_PLAYS = 100_000.0
_REF_CONV = 1_000.0


@dataclass(frozen=True)
class FitLearningProposal:
    """自学习候选分建议（只读，advisory）。

    `scores` 只含可学的三维（traffic/conv/load）；`safe` 无效果指标可学，
    恒为 None——调用方必须维持人工评估。
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


def propose_fit_from_metrics(
    metrics: Mapping[str, float] | None,
    *,
    sample_size: int = 0,
) -> FitLearningProposal | None:
    """由 effect metrics 聚合值计算四维候选分建议。

    返回 None 表示"数据不足，不触发自学习、维持人工分"（Q293 口径）。
    判据：无 metrics、或代理指标为零（plays≤0 且 inquiries+conversions≤0）。
    `safe` 恒不在建议里——安全维度无效果指标可学，维持人工评估。
    """
    if not metrics:
        return None
    plays = float(metrics.get("plays", 0) or 0)
    inquiries = float(metrics.get("inquiries", 0) or 0)
    conversions = float(metrics.get("conversions", 0) or 0)
    read_rate = float(metrics.get("read_rate", 0) or 0)

    if plays <= 0 and inquiries + conversions <= 0:
        return None

    scores: dict[str, float] = {}
    scores["traffic"] = _normalize(plays, _REF_PLAYS)
    scores["conv"] = _normalize(inquiries + conversions, _REF_CONV)
    scores["load"] = round(min(_SCORE_MAX, read_rate * _SCORE_MAX), 1)

    # 辅助信号：likes/comments/shares 互动量做置信度（0..1，不做主分）。
    likes = float(metrics.get("likes", 0) or 0)
    comments = float(metrics.get("comments", 0) or 0)
    shares = float(metrics.get("shares", 0) or 0)
    engagement = likes + comments + shares
    confidence = 0.0 if plays <= 0 else round(min(1.0, engagement / plays), 3)

    note = "advisory 自学习建议：traffic/conv/load 由效果指标映射；safe 维持人工（无指标可学）"
    return FitLearningProposal(
        scores=scores,
        confidence=confidence,
        sample_size=sample_size,
        note=note,
    )


__all__ = [
    "FIT_LEARNING_ENABLED",
    "FitLearningProposal",
    "propose_fit_from_metrics",
]
