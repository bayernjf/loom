"""Evaluation regression target adapters (M10-Q, Q77).

V1 没有进程内 LLM Skill 执行体；Golden Cases 打在具有确定性替身的 Skill 上：
PWC-SCORING（Q22/Q22a/Q22b 评分）、COMBO-VALIDATE（Q48 词表匹配）、
DIM-MERGE（PT-FP-PLAN-V2.0 结构校验，Q78 WF-02 切片）、
CAT-RECOG（c1 加权 conf/三分支判定，Q79 WF-01 切片）、
TYPE-MATCH（c7 确定性纯函数：Layer3 覆盖率/兄弟继承/0.6 地板，Q81 WF-01 C7 切片）、
WF-03 段4 四 Skill（Q80）：ATOM-EXPAND（Q14 批次上限/Q15 达标停拓）、
ATOM-CANON（normalize_text 规范化）、ATOM-AFFINITY（Q16 低亲和/Q19 keeper）、
CONFLICT-PRECHECK（Q17 双轨定级/line 840 冲突三类）。真 LLM 切片后同一批
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


def _c7_coverage(raw: dict) -> float:
    from app.product.modeling.c7 import coverage

    return coverage(raw["required_fids"], raw.get("available_fids", []))


def _c7_pick_sibling(raw: dict) -> dict | None:
    from app.product.modeling.c7 import pick_sibling

    return pick_sibling(raw["siblings"])


def _c7_layer3_floor(raw: dict) -> float:
    from app.product.modeling.c7 import layer3_coverage_floor

    return layer3_coverage_floor()


def _atom_default_batch_size(raw: dict) -> dict:
    from app.product.atom.atom_rules import default_batch_size

    return {"batch_size": default_batch_size(sensitive=raw["sensitive"])}


def _atom_target_reached(raw: dict) -> dict:
    from app.product.atom.atom_rules import target_reached

    return {
        "reached": target_reached(raw["approved_count"], raw["target_atom_max"])
    }


def _atom_normalize(raw: dict) -> str:
    from app.product.atom.atom_rules import normalize_text

    return normalize_text(raw["content"])


def _atom_is_low_affinity(raw: dict) -> dict:
    from app.product.atom.atom_rules import is_low_affinity

    return {"low_affinity": is_low_affinity(raw.get("affinity"))}


def _atom_pick_keeper(raw: dict) -> dict:
    from types import SimpleNamespace

    from app.product.atom.atom_rules import pick_cluster_keeper

    items = [SimpleNamespace(affinity=item.get("affinity")) for item in raw["items"]]
    keeper = pick_cluster_keeper(items)
    return {"keeper_index": items.index(keeper)}


def _atom_grade_risk(raw: dict) -> dict:
    from app.product.atom.atom_rules import WordlistHit, grade_risk

    hits = [WordlistHit(**h) for h in raw.get("hits", [])]
    grade = grade_risk(raw["content"], raw["ai_level"], hits)
    return {
        "level": grade.level,
        "source": grade.source,
        "banned": grade.banned,
    }


def _atom_conflicts_for(raw: dict) -> list:
    from app.product.atom.atom_rules import RiskGrade, WordlistHit, conflicts_for

    hits = [WordlistHit(**h) for h in raw.get("hits", [])]
    grade = RiskGrade(level=raw["level"], source=raw["source"], hits=hits)
    return [
        {"type": ctype, "status": cstatus}
        for ctype, cstatus in conflicts_for(grade, has_evidence=raw["has_evidence"])
    ]


TARGETS: dict[str, Callable[[dict], object]] = {
    "score_combo": _score_combo,
    "is_duplicate": _is_duplicate,
    "overlap_ratio": _overlap_ratio,
    "max_overlap": _max_overlap,
    "match_words": _match_words,
    "evaluate_plan": _evaluate_plan,
    "weighted_conf": _weighted_conf,
    "decide_branch": _decide_branch,
    # WF-01 TYPE-MATCH / C7（Q81）
    "c7_coverage": _c7_coverage,
    "c7_pick_sibling": _c7_pick_sibling,
    "c7_layer3_floor": _c7_layer3_floor,
    # WF-03 段4（Q80）
    "atom_default_batch_size": _atom_default_batch_size,
    "atom_target_reached": _atom_target_reached,
    "atom_normalize": _atom_normalize,
    "atom_is_low_affinity": _atom_is_low_affinity,
    "atom_pick_keeper": _atom_pick_keeper,
    "atom_grade_risk": _atom_grade_risk,
    "atom_conflicts_for": _atom_conflicts_for,
}
