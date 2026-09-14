"""段10 合规清洗纯规则：Q50 三层优先序（国家>平台>底座，不可配置）、
同级从严（Q36）、block_required 判定（PT-COMPLIANCE-V2.0）、Q49 敏感领域触发。
"""

# Q50：国家法规 > 平台规则 > 通用底座默认（固定优先序，不可配置）。
LAYER_COUNTRY = "country"
LAYER_PLATFORM = "platform"
LAYER_BASE = "base"
LAYER_PRIORITY = {LAYER_COUNTRY: 0, LAYER_PLATFORM: 1, LAYER_BASE: 2}

# Q36：同级冲突取最严——禁用严于降级，critical 严于 high。
ACTION_SEVERITY = {"ban": 0, "downgrade": 1}
LEVEL_SEVERITY = {"critical": 0, "high": 1}

# CCR 报告状态（05 无段10 状态机原文【实现补】）。
REPORT_CLEAN = "clean"
REPORT_DOWNGRADE_PENDING = "downgrade_pending"
REPORT_APPROVED = "approved"
REPORT_BLOCKED = "blocked"

LAW_PENDING = "pending"
LAW_APPROVED = "approved"
LAW_REJECTED = "rejected"

# Q49：法审待办 48h（24h 黄/48h 升级上级；黄色为看板态，sweep 升级随 M10 SLA 引擎）。
LAW_REVIEW_DUE_HOURS = 48
ROLE_INTERNAL_COMPLIANCE = "internal_compliance"
TODO_TYPE_LAW_REVIEW = "law_review"
# Q51：词表生效即扫命中 active 快照 → 提请 BO-07 强制重冻（wordlist_hit）。
TODO_TYPE_WORDLIST_RESCAN = "wordlist_rescan"
REASON_WORDLIST_HIT = "wordlist_hit"


def resolve_word(entries: list) -> object:
    """同一词命中多条时选生效裁决条目：先比 Q50 层级，同级取最严（Q36）。"""
    return min(
        entries,
        key=lambda e: (
            LAYER_PRIORITY[e.layer],
            ACTION_SEVERITY[e.action],
            LEVEL_SEVERITY[e.level],
        ),
    )


def resolve_hits(matched: list) -> list:
    """matched: 同一文本上 match_words 命中的词条；按词分组裁决，返回每词一条。"""
    by_word: dict[str, list] = {}
    for e in matched:
        by_word.setdefault(e.word, []).append(e)
    return [resolve_word(rows) for rows in by_word.values()]


def evaluate(entries: list, text_blob: str) -> dict:
    """确定性子串匹配 + 三层裁决。ban 命中 → block_required（一票否决，line 2029）。

    降级只产建议（CLAIM-DOWNGRADE），不改动文本、不自动放行，须人工 approval。
    直接对词条对象匹配（需携带 Q50 裁决所需 layer/entry_id/country）。
    """
    haystack = text_blob.casefold()
    matched = [e for e in entries if e.word and e.word.casefold() in haystack]
    resolved = resolve_hits(matched)
    bans = [
        {
            "word": e.word,
            "level": e.level,
            "layer": e.layer,
            "country": e.country,
            "entry_id": e.entry_id,
        }
        for e in resolved
        if e.action == "ban"
    ]
    downgrades = [
        {
            "word": e.word,
            "level": e.level,
            "layer": e.layer,
            "country": e.country,
            "downgrade_target": e.downgrade_target,
            "entry_id": e.entry_id,
        }
        for e in resolved
        if e.action == "downgrade"
    ]
    if bans:
        status = REPORT_BLOCKED
    elif downgrades:
        status = REPORT_DOWNGRADE_PENDING
    else:
        status = REPORT_CLEAN
    return {
        "status": status,
        "block_required": bool(bans),
        "bans": bans,
        "downgrades": downgrades,
    }


def applicable_to_market(entry, country: str | None) -> bool:
    """分市场独立判（PT-COMPLIANCE-V2.0）：词条国家为空=全市场通用，否则按市场取。"""
    return entry.country is None or entry.country == country


def normalize_layer(layer: str | None, country: str | None) -> str:
    """词层缺省：带国家的词条归国家法规层，其余归底座默认【实现补：M4 表无 layer 列】。"""
    if layer is not None:
        if layer not in LAYER_PRIORITY:
            raise ValueError(f"unknown compliance layer: {layer}")
        return layer
    return LAYER_COUNTRY if country else LAYER_BASE


def match_sensitive_domain(
    industry_tag: str | None, sensitive: bool, active_domain_codes: set[str]
) -> str | None:
    """Q49：产品属敏感领域清单即触发法审；sensitive_industry 旗标兜底（领域=行业标或兜底码）。"""
    if industry_tag and industry_tag in active_domain_codes:
        return industry_tag
    if sensitive:
        return industry_tag or "sensitive_other"
    return None
