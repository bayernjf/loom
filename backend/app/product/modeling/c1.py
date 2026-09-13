"""段2 C1 识别的纯逻辑：加权 conf、三分支判定（Q1/Q2/Q3）。

不碰数据库；权重/阈值由调用方从配置表读取后传入。
AI Skill（WF-01 六步）的信号提取在 M10 skill 通道接入，
本模块只消费"每启用信号一个 0..1 分"的结构化结果。
"""

from dataclasses import dataclass

# Q9 全局配置化要求的临时落点；M10 配置中心上线后迁移为后台配置（02 §C2）。
COLD_START_FLOOR = 0.6
TOP_GAP_CONTRADICTION = 0.1

BRANCH_DIRECT_APPROVE = "direct_approve"
BRANCH_OPS_ASSIST = "ops_assist"
BRANCH_COLD_START = "cold_start"


class WeightSumError(Exception):
    """Q2：启用信号权重之和必须精确等于 1，不等于 1 拒绝保存（不自动归一化）。"""


class MissingSignalScore(Exception):
    """每个启用信号必须有打分；缺失无法算 conf（Q2）。"""


def validate_enabled_weights(weights: dict[str, float]) -> None:
    total = round(sum(weights.values()), 4)
    if total != 1.0:
        raise WeightSumError(f"enabled signal weights must sum to 1.0 exactly, got {total}")


def weighted_conf(signal_scores: dict[str, float], weights: dict[str, float]) -> float:
    missing = sorted(set(weights) - set(signal_scores))
    if missing:
        raise MissingSignalScore(f"missing scores for enabled signals: {missing}")
    return round(sum(weights[key] * signal_scores[key] for key in weights), 4)


@dataclass(frozen=True)
class BranchDecision:
    branch: str
    conf: float
    top_gap: float | None


def decide_branch(
    *,
    conf: float,
    threshold: float,
    top_candidates: list[dict] | None = None,
) -> BranchDecision:
    """Q1/Q3 三分支：conf≥阈值 → direct_approve；[0.6,阈值) 或 Top1-Top2 差<0.1
    → ops_assist；conf<0.6 → cold_start。"""
    top_gap: float | None = None
    contradiction = False
    if top_candidates:
        ranked = sorted(
            (float(c["conf"]) for c in top_candidates), reverse=True
        )
        if len(ranked) >= 2:
            top_gap = round(ranked[0] - ranked[1], 4)
            contradiction = top_gap < TOP_GAP_CONTRADICTION

    if conf < COLD_START_FLOOR:
        branch = BRANCH_COLD_START
    elif conf < threshold or contradiction:
        branch = BRANCH_OPS_ASSIST
    else:
        branch = BRANCH_DIRECT_APPROVE
    return BranchDecision(branch=branch, conf=conf, top_gap=top_gap)
