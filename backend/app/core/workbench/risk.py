"""跨 target_type 风险归一口径（Q93/C1.37 接缝②，Q70 风险+时间排序）。

四档 critical/high/medium/low（沿用 atom RISK_LEVELS），各型派生规则：
- atom_batch：批内 items.ai_risk 最高档；
- c1_recognition：payload.industry 命中 c1_industry_thresholds.sensitive
  归 critical 桶（Q70“敏感行业/critical”），否则 low；行业字典无该行按非敏感；
- pwc_combo/field_plan/c7_layer4：payload 无风险信号，归 low（不编造）。

risk_reason 给机读来源码，便于审计与前端展示区分。
"""

from app.product.atom.atom_rules import (
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
)

RISK_RANK = {
    RISK_CRITICAL: 3,
    RISK_HIGH: 2,
    RISK_MEDIUM: 1,
    RISK_LOW: 0,
}

REASON_ATOM_MAX = "atom_batch.max_ai_risk"
REASON_SENSITIVE_INDUSTRY = "c1_recognition.sensitive_industry"
REASON_INDUSTRY_NOT_SENSITIVE = "c1_recognition.industry_not_sensitive"
REASON_INDUSTRY_UNKNOWN = "c1_recognition.industry_unregistered"
REASON_NO_SIGNAL = "no_risk_signal"

# risk_rank 达到此线禁批量（承接 Q80 记录“Q70 high/critical 禁批量”）。
BATCH_RISK_CEILING = RISK_RANK[RISK_HIGH]


def atom_batch_risk(payload: dict) -> tuple[str, str]:
    levels = [
        item.get("ai_risk", RISK_LOW)
        for item in payload.get("items", [])
        if isinstance(item, dict)
    ]
    top = max(levels, key=lambda level: RISK_RANK.get(level, 0)) if levels else RISK_LOW
    return top, REASON_ATOM_MAX


def c1_recognition_risk(payload: dict, *, sensitive_industries: set[str]) -> tuple[str, str]:
    industry = payload.get("industry")
    if not industry:
        return RISK_LOW, REASON_INDUSTRY_UNKNOWN
    if industry in sensitive_industries:
        return RISK_CRITICAL, REASON_SENSITIVE_INDUSTRY
    return RISK_LOW, REASON_INDUSTRY_NOT_SENSITIVE


def static_low_risk() -> tuple[str, str]:
    return RISK_LOW, REASON_NO_SIGNAL


def derive_risk(
    target_type: str, payload: dict, *, sensitive_industries: set[str]
) -> tuple[str, str]:
    if target_type == "atom_batch":
        return atom_batch_risk(payload)
    if target_type == "c1_recognition":
        return c1_recognition_risk(
            payload, sensitive_industries=sensitive_industries
        )
    return static_low_risk()
