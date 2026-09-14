"""段7/8 静态底表纯逻辑：发布位/平台规则/PCP 权重的机械判定。

- Q34：fit_score = Σ(四维分 × 目的权重)，权重矩阵按 contentGoals 配置、Σ=1 强校验；
- Q36：规则冲突同级取最严（blocked > partial）；保存时静态查重（同层级同条件不同结论）；
- Q40：17 池权重 Σ≤1.0 统一校验器（入库前强制，拒绝不合格，对齐 Q2 风格）。

选择器优先级（line 1383，低→高）：slotType > platform > platform+slotType > slotId；
country 为横切 modifier。动态信号/fit_score 学习/每周重算均不在 V1（08 M11）。
"""

WEIGHT_KEYS_17: tuple[str, ...] = (
    "goal",
    "action",
    "struct",
    "intensity",
    "rhythm",
    "tone",
    "emotion",
    "style",
    "perspective",
    "stage",
    "title",
    "hook",
    "opening",
    "mid1",
    "mid2",
    "mid3",
    "ending",
)

FIT_DIMS: tuple[str, ...] = ("traffic", "safe", "conv", "load")

# 选择器层级（低→高）；命中多层时高优先级覆盖低优先级（line 1383）。
LEVEL_SLOT_TYPE = "slot_type"
LEVEL_PLATFORM = "platform"
LEVEL_PLATFORM_SLOT_TYPE = "platform_slot_type"
LEVEL_SLOT = "slot"
SELECTOR_LEVELS: tuple[str, ...] = (
    LEVEL_SLOT_TYPE,
    LEVEL_PLATFORM,
    LEVEL_PLATFORM_SLOT_TYPE,
    LEVEL_SLOT,
)
LEVEL_PRIORITY = {level: i for i, level in enumerate(SELECTOR_LEVELS)}

EFFECT_BLOCKED = "blocked"
EFFECT_PARTIAL = "partial"
EFFECT_SEVERITY = {EFFECT_PARTIAL: 0, EFFECT_BLOCKED: 1}

GATE_PENDING = "pending_gate"
GATE_APPROVED = "approved"

SUM_TOLERANCE = 1e-9


def validate_weights_17(weights: dict) -> list[str]:
    """Q40 统一校验器：键必须落在 17 池内、值 0..1、Σ≤1.0。返回违规码数组。"""
    violations: list[str] = []
    unknown = sorted(set(weights) - set(WEIGHT_KEYS_17))
    if unknown:
        violations.append(f"unknown_weight_keys:{','.join(unknown)}")
    for key, value in weights.items():
        if not isinstance(value, (int, float)) or value < 0 or value > 1:
            violations.append(f"weight_out_of_range:{key}")
    total = sum(v for v in weights.values() if isinstance(v, (int, float)))
    if total > 1.0 + SUM_TOLERANCE:
        violations.append("weight_sum_exceeds_1")
    return violations


def validate_fit_weights(weights: dict) -> list[str]:
    """Q34 目的权重矩阵：四维齐全、值 0..1、Σ=1（Q2 风格强校验，不归一化）。"""
    violations: list[str] = []
    missing = [d for d in FIT_DIMS if d not in weights]
    if missing:
        violations.append(f"missing_fit_dims:{','.join(missing)}")
    for key, value in weights.items():
        if key not in FIT_DIMS:
            violations.append(f"unknown_fit_dim:{key}")
        elif not isinstance(value, (int, float)) or value < 0 or value > 1:
            violations.append(f"weight_out_of_range:{key}")
    if not missing:
        total = sum(weights[d] for d in FIT_DIMS)
        if abs(total - 1.0) > SUM_TOLERANCE:
            violations.append("weight_sum_not_1")
    return violations


def compute_fit_score(slot, weights: dict) -> float:
    """Q34：fit_score = Σ(维度分 × 权重)。派生值，不落库（10 §2.4 建议）。"""
    return (
        slot.traffic * weights["traffic"]
        + slot.safe * weights["safe"]
        + slot.conv * weights["conv"]
        + slot.load * weights["load"]
    )


def condition_key(rule) -> tuple:
    """同层级同条件的身份键；country 为横切 modifier，参与同一格子的判定。"""
    return (
        rule.selector_level,
        rule.platform,
        rule.slot_type,
        rule.slot_id,
        rule.country,
    )


def find_conflicts(existing, candidate) -> list:
    """Q36 保存时静态查重：同层级同条件但结论不同的 active 规则。"""
    key = condition_key(candidate)
    return [
        r
        for r in existing
        if r.status == "active"
        and condition_key(r) == key
        and r.effect != candidate.effect
    ]


def resolve_effect(matched) -> str | None:
    """Q36：命中多条取最严（blocked > partial）；无命中返回 None（native 默认不存）。"""
    if not matched:
        return None
    best = max(
        matched,
        key=lambda r: (LEVEL_PRIORITY[r.selector_level], EFFECT_SEVERITY[r.effect]),
    )
    highest = LEVEL_PRIORITY[best.selector_level]
    same_level = [r for r in matched if LEVEL_PRIORITY[r.selector_level] == highest]
    return max(same_level, key=lambda r: EFFECT_SEVERITY[r.effect]).effect


def validate_selector(level: str, platform, slot_type, slot_id) -> list[str]:
    """各层级必填的选择器字段；slotId 级必须定位到具体发布位。"""
    violations: list[str] = []
    if level not in SELECTOR_LEVELS:
        return [f"unknown_selector_level:{level}"]
    if level in (LEVEL_PLATFORM, LEVEL_PLATFORM_SLOT_TYPE, LEVEL_SLOT) and not platform:
        violations.append("platform_required")
    if level in (LEVEL_SLOT_TYPE, LEVEL_PLATFORM_SLOT_TYPE) and not slot_type:
        violations.append("slot_type_required")
    if level == LEVEL_SLOT and not slot_id:
        violations.append("slot_id_required")
    return violations
