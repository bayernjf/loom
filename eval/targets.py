"""Evaluation regression target adapters (M10-Q, Q77).

V1 没有进程内 LLM Skill 执行体；Golden Cases 打在 WF-04 中具有确定性
替身的两个 Skill 上：PWC-SCORING（Q22/Q22a/Q22b 评分）与
COMBO-VALIDATE（Q48 词表匹配）。真 LLM 切片后同一批 YAML 案例改打
Skill 输出，只需在此注册表增改适配器，案例数据不动。
"""

from collections.abc import Callable


def _score_combo(raw: dict) -> dict:
    from app.product.condition.pwc_rules import score_combo

    out = score_combo(
        logic=raw.get("logic"),
        fit=raw.get("fit"),
        max_pool_overlap=raw["max_pool_overlap"],
        w_logic=raw.get("w_logic"),
        w_fit=raw.get("w_fit"),
        category_multiplier=raw.get("category_multiplier"),
    )
    return {"scored": out.scored, "score": out.score, "detail": out.detail}


def _is_duplicate(raw: dict) -> bool:
    from app.product.condition.pwc_rules import is_duplicate

    return is_duplicate(raw["max_pool_overlap"])


def _overlap_ratio(raw: dict) -> float:
    from app.product.condition.pwc_rules import overlap_ratio

    return overlap_ratio(frozenset(raw["a"]), frozenset(raw["b"]))


def _max_overlap(raw: dict) -> float:
    from app.product.condition.pwc_rules import max_overlap

    return max_overlap(
        frozenset(raw["combo"]), [frozenset(s) for s in raw["pool_combos"]]
    )


def _match_words(raw: dict) -> list[dict]:
    from app.core.compliance_wordlist.models import ComplianceWordlistEntry
    from app.core.compliance_wordlist.service import match_words

    entries = [
        ComplianceWordlistEntry(word=e["word"], level=e["level"], action=e["action"])
        for e in raw["entries"]
    ]
    hits = match_words(raw["content"], entries)
    return [{"word": h.word, "level": h.level, "action": h.action} for h in hits]


TARGETS: dict[str, Callable[[dict], object]] = {
    "score_combo": _score_combo,
    "is_duplicate": _is_duplicate,
    "overlap_ratio": _overlap_ratio,
    "max_overlap": _max_overlap,
    "match_words": _match_words,
}
