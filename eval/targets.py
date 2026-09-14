"""Evaluation regression target adapters (M10-Q, Q77).

V1 没有进程内 LLM Skill 执行体；Golden Cases 打在具有确定性替身的 Skill 上：
PWC-SCORING（Q22/Q22a/Q22b 评分）、COMBO-VALIDATE（Q48 词表匹配）、
DIM-MERGE（PT-FP-PLAN-V2.0 结构校验，Q78 WF-02 切片）、
CAT-RECOG（c1 加权 conf/三分支判定，Q79 WF-01 切片）。真 LLM 切片后同一批
YAML 案例改打 Skill 输出，只需在此注册表增改适配器，案例数据不动。
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


def _evaluate_plan(raw: dict) -> dict:
    from app.product.fieldpool.planning import DimInput, evaluate_plan

    result = evaluate_plan(
        [DimInput(**d) for d in raw["dimensions"]],
        sensitive=raw.get("sensitive", False),
        enabled_routes=frozenset(raw["enabled_routes"]),
        active_fids=frozenset(raw.get("active_fids", [])),
    )
    return {
        "compliant": result.compliant,
        "violations": result.violations,
        "selected_count": len(result.selected),
        "backup_count": len(result.backup),
        "backup_fields": [e.dim.field_name for e in result.backup],
        "needs_detail_fields": [
            e.dim.field_name for e in result.selected if e.needs_detail
        ],
        "dup_fields": [e.dim.field_name for e in result.selected if e.dup],
    }


def _weighted_conf(raw: dict) -> float:
    from app.product.modeling.c1 import weighted_conf

    return weighted_conf(raw["scores"], raw["weights"])


def _decide_branch(raw: dict) -> dict:
    from app.product.modeling.c1 import decide_branch

    decision = decide_branch(
        conf=raw["conf"],
        threshold=raw["threshold"],
        top_candidates=raw.get("candidates"),
        cold_floor=raw.get("cold_floor", 0.6),
        top_gap_line=raw.get("top_gap_line", 0.1),
    )
    return {
        "branch": decision.branch,
        "conf": decision.conf,
        "top_gap": decision.top_gap,
    }


TARGETS: dict[str, Callable[[dict], object]] = {
    "score_combo": _score_combo,
    "is_duplicate": _is_duplicate,
    "overlap_ratio": _overlap_ratio,
    "max_overlap": _max_overlap,
    "match_words": _match_words,
    "evaluate_plan": _evaluate_plan,
    "weighted_conf": _weighted_conf,
    "decide_branch": _decide_branch,
}
