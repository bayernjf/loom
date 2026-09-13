"""段5 PWC 条件包纯逻辑（无 DB/HTTP 依赖）。

依据：Q21（预筛→检测→评分→限量漏斗，单次 50/目标 100）、
Q22/Q22a/Q22b（score=(合理性0.6+多样性0.4)×品类乘数，乘数一期 1.0，
AI 分项缺失不凑分转人工 Gate）、Q23（重合占比 ≥0.8 标疑重）、
Q24（同平台+账号+发布位仅用 1 次、7 天 3 次冷却/14 天回待用、跨平台复用）、
Q25（contentGoals 5 类）、Q26（手拼跳预筛不豁免合规）、Q27（库容默认 100 可无上限）、
Q71（按分排序取用、target100/min70/critical50、补货冷却 5min）、line 1451。

WF-04 三 Skill（PWC-BUILDER/COMBO-VALIDATE/PWC-SCORING）的 AI 通道随 M10；
M5 接收结构化组合与 AI 分项分，做确定性合规检测、评分、去重、冷却与流转。

拍板值暂为常量，M10 迁配置中心（02 §C2：50/100、0.6/0.4、w1=w2=0.5、
0.8、7 天 3 次/14 天、5min）。
"""

from dataclasses import dataclass

# Q21：漏斗单次产出上限、待用池目标量（§C2 配置项）。
SINGLE_RUN_MAX = 50
POOL_TARGET = 100

# Q71：池健康度三档（line 1451）与补货防抖冷却。
POOL_MIN = 70
POOL_CRITICAL = 50
RESTOCK_COOLDOWN_MINUTES = 5

# Q27：待用池默认库容；None 表示运营显式配"无上限"。
DEFAULT_CAPACITY = 100

# Q22/Q22a：评分权重。
REASONABLENESS_WEIGHT = 0.6
DIVERSITY_WEIGHT = 0.4
W_LOGIC = 0.5
W_FIT = 0.5
CATEGORY_MULTIPLIER_DEFAULT = 1.0  # Q22：第一期各行业恒 1.0

# Q23：疑似重复线（第一期不用语义向量）。
DUP_OVERLAP_LINE = 0.8

# Q24：冷却三配置项。
COOLDOWN_WINDOW_DAYS = 7
COOLDOWN_HITS = 3
COOLDOWN_DURATION_DAYS = 14

# Q25：contentGoals 五类标准枚举（line 1090）；名称/颜色/配比上下限运营可维护。
GOAL_ENGAGEMENT = "ENGAGEMENT"
GOAL_CONVERSION = "CONVERSION"
GOAL_EDUCATION = "EDUCATION"
GOAL_TRUST = "TRUST"
GOAL_RETENTION = "RETENTION"
CONTENT_GOALS = (
    GOAL_ENGAGEMENT,
    GOAL_CONVERSION,
    GOAL_EDUCATION,
    GOAL_TRUST,
    GOAL_RETENTION,
)

# gate_status（line 1780 原列三值）。
GATE_PENDING = "pending"
GATE_BLOCKED = "blocked"
GATE_APPROVED = "approved"

# 生命周期状态（line 1780-1806；候选为漏斗内瞬态不落库，待入库原文仅列名【待补】）。
PWC_PENDING_GATE = "pending_gate"
PWC_READY = "ready"          # 待用
PWC_USED = "used"            # 已用（全目标平台用尽终态）
PWC_BLOCKED = "blocked"      # 阻断
PWC_ARCHIVED = "archived"    # 归档
# 冷却为"同平台"口径（Q24 跨平台仍可复用）：活在 platform_state，不做全局态。

ROLE_REVIEWER = "product_reviewer"  # PWC 人工 Gate
ROLE_OPERATIONS = "operations"      # 字典/库容配置/爆款手工标注/归档


def overlap_ratio(a: frozenset, b: frozenset) -> float:
    """Q23 重合原子数占比。

    原文只给"重合原子数占比"未定义分母【原文未给出】，实现取 Jaccard
    （|A∩B|/|A∪B|）【实现补】；空集对返回 0。多样性与疑重去重共用本函数（Q22b）。
    """
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def max_overlap(combo: frozenset, pool_combos: list[frozenset]) -> float:
    """多样性 = 1 − max(与待用池中各组合的重合占比)；池为空 max=0（Q22b）。"""
    if not pool_combos:
        return 0.0
    return max(overlap_ratio(combo, other) for other in pool_combos)


@dataclass
class ScoreOutcome:
    """PWC-SCORING 产物；AI 分项缺失时 scored=False，不凑分（Q22b）。"""

    scored: bool
    score: float | None
    detail: dict

    @property
    def needs_manual_gate(self) -> bool:
        return not self.scored


def score_combo(
    *,
    logic: float | None,
    fit: float | None,
    max_pool_overlap: float,
    w_logic: float = W_LOGIC,
    w_fit: float = W_FIT,
    category_multiplier: float = CATEGORY_MULTIPLIER_DEFAULT,
) -> ScoreOutcome:
    """Q22/Q22a/Q22b：合规前置在调用处处理，本函数只算加权分。

    逻辑合理性/场景情绪搭配任一 AI 分缺失 → 分项记 "—"、不出分，
    组合转人工 Gate（score 仅排序辅助，不做自动通过门槛）。
    """
    if logic is None or fit is None:
        return ScoreOutcome(
            scored=False,
            score=None,
            detail={
                "logic": "—" if logic is None else logic,
                "fit": "—" if fit is None else fit,
                "diversity": 1 - max_pool_overlap,
                "category_multiplier": category_multiplier,
                "w_logic": w_logic,
                "w_fit": w_fit,
            },
        )
    reasonableness = logic * w_logic + fit * w_fit
    diversity = 1 - max_pool_overlap
    score = (
        reasonableness * REASONABLENESS_WEIGHT
        + diversity * DIVERSITY_WEIGHT
    ) * category_multiplier
    return ScoreOutcome(
        scored=True,
        score=score,
        detail={
            "logic": logic,
            "fit": fit,
            "reasonableness": reasonableness,
            "diversity": diversity,
            "category_multiplier": category_multiplier,
            "w_logic": w_logic,
            "w_fit": w_fit,
        },
    )


def is_duplicate(max_pool_overlap: float) -> bool:
    """Q23：≥0.8 标疑似重复，保留分高者、低分降权入备选，人工可改判。"""
    return max_pool_overlap >= DUP_OVERLAP_LINE


def should_cooldown(recent_hits: int) -> bool:
    """Q24：冷却窗口内同平台消费次数达线即冷却。"""
    return recent_hits >= COOLDOWN_HITS


def cooldown_over(cooldown_until, now) -> bool:
    return cooldown_until is not None and cooldown_until <= now


def goals_intersect(pwc_goals: list[str], requested_goals: list[str] | None) -> bool:
    """Q25：消费时 PWC.goals 与请求目的取交集；不指定目的不过滤。"""
    if not requested_goals:
        return True
    return bool(set(pwc_goals) & set(requested_goals))


def all_platforms_used(used_platforms: set[str], target_platforms: list[str] | None) -> bool:
    """Q24：全部目标平台用过即转已用。

    目标平台清单原文未给出来源【原文未给出，待补】，实现为 PS 级配置项，
    未配置时不产生"已用"终态（跨平台可继续复用）【实现补】。
    """
    if not target_platforms:
        return False
    return set(target_platforms).issubset(used_platforms)


def pool_health(ready_count: int) -> str:
    """Q71/line 1451 池健康度三档。"""
    if ready_count < POOL_CRITICAL:
        return "critical"
    if ready_count < POOL_MIN:
        return "low"
    if ready_count < POOL_TARGET:
        return "healthy_below_target"
    return "target"
