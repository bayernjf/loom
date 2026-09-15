"""段4 纯逻辑单测：批次/亲和度/risk 双轨/冲突三类/Guard 10 项/同义簇/停拓。"""

import math

import pytest

from app.product.atom import atom_rules as r
from app.product.atom.atom_rules import WordlistHit


def test_default_batch_size_follows_sensitive_flag():
    assert r.default_batch_size(sensitive=True) == 20
    assert r.default_batch_size(sensitive=False) == 50


def test_low_affinity_flag_only_no_hard_cut():
    assert r.is_low_affinity(0.49) is True
    assert r.is_low_affinity(0.5) is False
    assert r.is_low_affinity(None) is False


def test_risk_grading_wordlist_forces_level_over_ai():
    hits = [WordlistHit(word="禁用词", level="critical", action="ban")]
    grade = r.grade_risk("含禁用词内容", "low", hits)
    assert grade.level == "critical"
    assert grade.source == "wordlist"
    assert grade.banned is True


def test_risk_grading_takes_highest_wordlist_level():
    hits = [
        WordlistHit(word="高", level="high", action="downgrade"),
        WordlistHit(word="禁用", level="critical", action="ban"),
    ]
    grade = r.grade_risk("x", "low", hits)
    assert grade.level == "critical"


def test_risk_grading_ai_fallback():
    grade = r.grade_risk("普通表达", "high", [])
    assert grade.level == "high"
    assert grade.source == "ai"
    assert grade.banned is False


def test_conflicts_critical_ban_is_blocked_disabled_expression():
    grade = r.RiskGrade(level="critical", source="wordlist",
                        hits=[WordlistHit("w", "critical", "ban")])
    conflicts = r.conflicts_for(grade, has_evidence=True)
    assert (r.CONFLICT_DISABLED_EXPRESSION, r.CONFLICT_BLOCKED) in conflicts


def test_conflicts_high_requires_single_review_and_evidence():
    grade = r.RiskGrade(level="high", source="ai")
    assert r.conflicts_for(grade, has_evidence=False) == [
        (r.CONFLICT_HIGH_RISK_SINGLE, r.CONFLICT_PENDING_GATE),
        (r.CONFLICT_EVIDENCE_REQUIRED, r.CONFLICT_BLOCKED),
    ]
    assert r.conflicts_for(grade, has_evidence=True) == [
        (r.CONFLICT_HIGH_RISK_SINGLE, r.CONFLICT_PENDING_GATE),
    ]


def test_low_risk_no_conflicts():
    grade = r.RiskGrade(level="low", source="ai")
    assert r.conflicts_for(grade, has_evidence=True) == []


def _guard_kwargs(**over):
    base = {
        "candidate_ps_id": "ps1",
        "expected_ps_id": "ps1",
        "candidate_pool_id": "pool1",
        "expected_pool_id": "pool1",
        "pool_gate": "approved",
        "candidate_status": r.CAND_PENDING_REVIEW,
        "conflict_types": set(),
        "approved_atom_id": None,
        "has_evidence": True,
        "bulk": False,
        "risk_level": "low",
    }
    base.update(over)
    return base


def test_guard_passes_for_clean_candidate():
    assert r.approve_guard_checks(**_guard_kwargs()) == []


def test_guard_blocks_all_violations():
    violations = set(r.approve_guard_checks(**_guard_kwargs(
        candidate_ps_id="ps-other",
        candidate_pool_id="pool-other",
        pool_gate="pending_gate",
        candidate_status=r.CAND_REJECTED,
        conflict_types={r.CONFLICT_DISABLED_EXPRESSION},
        approved_atom_id="atom-1",
        has_evidence=False,
        bulk=True,
        risk_level="critical",
    )))
    assert violations == {
        r.GUARD_WRONG_PS,
        r.GUARD_WRONG_POOL,
        r.GUARD_POOL_NOT_APPROVED,
        r.GUARD_STATUS_REJECTED,
        r.GUARD_BLOCKED_CONFLICT,
        r.GUARD_ALREADY_APPROVED,
        r.GUARD_EVIDENCE_MISSING,
        r.GUARD_BULK_HIGH_CRITICAL,
    }


def test_guard_non_approvable_status():
    violations = r.approve_guard_checks(**_guard_kwargs(
        candidate_status=r.CAND_APPROVED
    ))
    assert violations == [r.GUARD_NOT_APPROVABLE]


def test_guard_high_allowed_single_but_not_bulk():
    single = r.approve_guard_checks(**_guard_kwargs(
        candidate_status=r.CAND_PENDING_REVIEW, risk_level="high",
        conflict_types={r.CONFLICT_HIGH_RISK_SINGLE},
    ))
    assert r.GUARD_BULK_HIGH_CRITICAL not in single
    bulk = r.approve_guard_checks(**_guard_kwargs(
        bulk=True, risk_level="high",
        candidate_status=r.CAND_PENDING_REVIEW,
        conflict_types={r.CONFLICT_HIGH_RISK_SINGLE},
    ))
    assert r.GUARD_BULK_HIGH_CRITICAL in bulk


class _Item:
    def __init__(self, affinity):
        self.affinity = affinity


def test_cluster_keeper_is_highest_affinity():
    items = [_Item(0.4), _Item(0.9), _Item(0.7)]
    assert r.pick_cluster_keeper(items).affinity == 0.9


def test_cluster_keeper_none_affinity_ranks_last_and_tie_keeps_order():
    a, b, c = _Item(0.5), _Item(None), _Item(0.5)
    keeper = r.pick_cluster_keeper([a, b, c])
    assert keeper is a


def test_target_reached():
    assert r.target_reached(30, 30) is True
    assert r.target_reached(29, 30) is False


def test_normalize_dedup():
    assert r.normalize_text("  Hello   World ") == "hello world"
    assert r.normalize_text("hello  world") == "hello world"


# ---------- Q86：embedding 相似度 / 同维成簇 ----------

def test_cosine_basic_and_clamped():
    assert r.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert r.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    with pytest.raises(ValueError):
        r.cosine_similarity([1.0], [1.0, 0.0])


def test_cosine_zero_vector_is_zero_not_nan():
    assert r.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_max_affinity_none_basis_is_none_and_rounds_6dp():
    assert r.max_affinity([1.0, 0.0], []) is None
    val = r.max_affinity([1.0, 0.0], [[0.5, 0.5], [1.0, 0.0]])
    assert val == 1.0


def test_assign_clusters_only_groups_pairs_above_line_and_respects_labels():
    line = r.cluster_line()
    assert line == 0.9

    def _vec_at(cos: float) -> list[float]:
        # 与 [1,0] 夹角余弦 cos 的二维单位向量。
        return [cos, math.sqrt(max(0.0, 1 - cos * cos))]

    base = [1.0, 0.0]
    near = _vec_at(0.95)
    far = _vec_at(0.2)
    ids = r.assign_clusters([base, near, far], line=line)
    assert ids[0] is not None and ids[0] == ids[1]
    assert ids[2] is None

    # labels 不同：即使余弦过线也不跨维成簇。
    other_near = _vec_at(0.99)
    ids = r.assign_clusters([base, other_near], line=line, labels=["d1", "d2"])
    assert ids == [None, None]
