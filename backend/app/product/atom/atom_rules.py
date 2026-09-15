"""段4 原子拓展纯逻辑（无 DB/HTTP 依赖）。

依据：atom8（line 1454，docs/13 §1.3）、PT-ATOM-EXP-V1.3（line 2013）、
approveAtomGuard 10 项（line 2633）、AtomConflict（line 840）、
Q14（批次 20/50）/Q15（达标停拓）/Q16（亲和度 0.5 提醒）/
Q17（risk 双轨，词表强制、AI 兜底、只升不降）/Q18（证据 7 天）/
Q19（同义簇留高亲和者，余为 alias）/Q20（冻结/合规/废弃权限）。

WF-03 四个 Skill（ATOM-EXPAND/CANON/AFFINITY/CONFLICT-PRECHECK）的 AI 产物
由 M10 skill7 通道接入；M4 只接收结构化候选并做确定性定级、冲突、Guard 与流转。
Q86 起 AFFINITY 的 affinity/cluster 由 embedding 向量在本地确定性算出
（成簇线 atom.cluster_line 借 Q10 0.9，原文未给【待补】）。

拍板值经配置中心热更（02 §C2 已登记 20/50、0.5、7 天、15-30；M10c 接入）。
"""

import math
import uuid
from dataclasses import dataclass, field

from app.core.config_center.knobs import knob


# Q14/Q16/Q18 拍板值经配置中心热更（02 §C2）。
def batch_size_sensitive() -> int:
    return knob("atom.batch_size_sensitive")


def batch_size_default() -> int:
    return knob("atom.batch_size_default")


def low_affinity_line() -> float:
    return knob("atom.low_affinity_line")


def evidence_timeout_days() -> int:
    return knob("atom.evidence_timeout_days")


def cluster_line() -> float:
    # Q86：成簇线原文未给【待补】，借 Q10 字段去重 0.9 同义线（02 §C2）。
    return knob("atom.cluster_line")

# Q17：原文只给 critical/high；medium/low 为实现补全等级，标【实现补】。
RISK_CRITICAL = "critical"
RISK_HIGH = "high"
RISK_MEDIUM = "medium"
RISK_LOW = "low"
RISK_LEVELS = (RISK_CRITICAL, RISK_HIGH, RISK_MEDIUM, RISK_LOW)
_RISK_RANK = {RISK_CRITICAL: 3, RISK_HIGH: 2, RISK_MEDIUM: 1, RISK_LOW: 0}

# 产品事实原子（容量/成分/浓度/疣类型/品牌）：引用数恒=1，严禁跨产品复用
# （line 11189）；通用人类表达原子可作模板派生各自实例。
FACT_CAPACITY = "capacity"
FACT_INGREDIENT = "ingredient"
FACT_CONCENTRATION = "concentration"
FACT_WART_TYPE = "wart_type"
FACT_BRAND = "brand"
PRODUCT_FACT_TYPES = frozenset(
    {FACT_CAPACITY, FACT_INGREDIENT, FACT_CONCENTRATION, FACT_WART_TYPE, FACT_BRAND}
)

# 候选状态：PT-ATOM-EXP 仅产 candidate，不直接写 ProductAtomInstance。
CAND_PENDING_REVIEW = "pending_review"
CAND_PENDING_EVIDENCE = "pending_evidence"
CAND_APPROVED = "approved"
CAND_REJECTED = "rejected"
CAND_MERGED = "merged"  # Q19：被合并词条不删，作为 keeper 的 alias

# 正式原子状态（atom8；草稿/待审核活在候选侧）。
ATOM_APPROVED = "approved"
ATOM_FROZEN = "frozen"
ATOM_DEPRECATED = "deprecated"
ATOM_REJECTED = "rejected"
ATOM_COMPLIANCE_SUSPENDED = "compliance_suspended"
ATOM_ARCHIVED = "archived"

# AtomConflict（line 840）。
CONFLICT_DISABLED_EXPRESSION = "disabled_expression"  # critical→驳回+合规审计
CONFLICT_HIGH_RISK_SINGLE = "high_risk_single_review"  # high→单条 HumanGate
CONFLICT_EVIDENCE_REQUIRED = "evidence_required"  # high→补证据或驳回
CONFLICT_BLOCKED = "blocked"
CONFLICT_PENDING_GATE = "pending_gate"

BLOCKED_CONFLICTS = frozenset(
    {CONFLICT_DISABLED_EXPRESSION, CONFLICT_EVIDENCE_REQUIRED}
)

ROLE_REVIEWER = "product_reviewer"  # 原子 Gate（06 §4）
ROLE_OPERATIONS = "operations"  # Q20 冻结/解冻
ROLE_COMPLIANCE = "internal_compliance"  # Q20 合规暂停/恢复；Q48 词表维护
WORDLIST_EDITOR_ROLES = frozenset({ROLE_OPERATIONS, ROLE_COMPLIANCE})

REJECT_EVIDENCE_TIMEOUT = "evidence_timeout"

# approveAtomGuard 违规码（顺序对应 line 2633 的 10 项；⑩writeAudit 在 service 落）。
GUARD_WRONG_PS = "wrong_product_space"
GUARD_WRONG_POOL = "wrong_field_pool"
GUARD_POOL_NOT_APPROVED = "pool_not_approved"
GUARD_STATUS_REJECTED = "status_rejected"
GUARD_NOT_APPROVABLE = "gate_not_approvable"
GUARD_BLOCKED_CONFLICT = "blocked_conflict"
GUARD_ALREADY_APPROVED = "approved_id_present"
GUARD_EVIDENCE_MISSING = "evidence_missing"
GUARD_BULK_HIGH_CRITICAL = "bulk_high_critical_forbidden"


def default_batch_size(*, sensitive: bool) -> int:
    return batch_size_sensitive() if sensitive else batch_size_default()


def normalize_text(text: str) -> str:
    """同批次去重/事实原子跨产品查重的规范化：去空白、小写（ATOM-CANON 占位）。"""
    return " ".join(text.strip().casefold().split())


def is_low_affinity(affinity: float | None) -> bool:
    return affinity is not None and affinity < low_affinity_line()


@dataclass
class WordlistHit:
    word: str
    level: str
    action: str


@dataclass
class RiskGrade:
    level: str
    source: str  # wordlist / ai
    hits: list[WordlistHit] = field(default_factory=list)

    @property
    def banned(self) -> bool:
        # critical 且词表处置=ban → disabled_expression（line 840）。
        return any(h.level == RISK_CRITICAL and h.action == "ban" for h in self.hits)


def grade_risk(content: str, ai_level: str, hits: list[WordlistHit]) -> RiskGrade:
    """Q17 双轨：命中词表按词表等级强制定级（AI 无权改）；未命中用 AI 判级。"""
    if hits:
        level = max((h.level for h in hits), key=lambda x: _RISK_RANK[x])
        return RiskGrade(level=level, source="wordlist", hits=hits)
    return RiskGrade(level=ai_level, source="ai")


def conflicts_for(grade: RiskGrade, *, has_evidence: bool) -> list[tuple[str, str]]:
    """返回 [(conflict_type, status)]；line 840 三类。"""
    out: list[tuple[str, str]] = []
    if grade.banned:
        out.append((CONFLICT_DISABLED_EXPRESSION, CONFLICT_BLOCKED))
    if grade.level == RISK_HIGH:
        out.append((CONFLICT_HIGH_RISK_SINGLE, CONFLICT_PENDING_GATE))
        if not has_evidence:
            out.append((CONFLICT_EVIDENCE_REQUIRED, CONFLICT_BLOCKED))
    return out


def approve_guard_checks(
    *,
    candidate_ps_id: str,
    expected_ps_id: str,
    candidate_pool_id: str,
    expected_pool_id: str,
    pool_gate: str,
    candidate_status: str,
    conflict_types: set[str],
    approved_atom_id: str | None,
    has_evidence: bool,
    bulk: bool,
    risk_level: str,
) -> list[str]:
    """approveAtomGuard ①-⑨（⑩变更前 writeAudit 由 service 保证）。"""
    violations: list[str] = []
    if candidate_ps_id != expected_ps_id:
        violations.append(GUARD_WRONG_PS)
    if candidate_pool_id != expected_pool_id:
        violations.append(GUARD_WRONG_POOL)
    if pool_gate != "approved":
        violations.append(GUARD_POOL_NOT_APPROVED)
    if candidate_status == CAND_REJECTED:
        violations.append(GUARD_STATUS_REJECTED)
    elif candidate_status not in (CAND_PENDING_REVIEW, CAND_PENDING_EVIDENCE):
        violations.append(GUARD_NOT_APPROVABLE)
    if conflict_types & BLOCKED_CONFLICTS:
        violations.append(GUARD_BLOCKED_CONFLICT)
    if approved_atom_id is not None:
        violations.append(GUARD_ALREADY_APPROVED)
    if not has_evidence:
        violations.append(GUARD_EVIDENCE_MISSING)
    # ⑨high/critical 单条审批：批量端点上遇到 high/critical 即违规（Q70）。
    if bulk and risk_level in (RISK_HIGH, RISK_CRITICAL):
        violations.append(GUARD_BULK_HIGH_CRITICAL)
    return violations


def pick_cluster_keeper(items: list) -> tuple | None:
    """Q19：同义簇推荐保留项=亲和度最高者；None 亲和度排最后，并列保持原序。"""
    if not items:
        return None

    def _key(i: int, item) -> tuple[float, int]:
        affinity = item.affinity if item.affinity is not None else -1.0
        return affinity, -i

    return max(enumerate(items), key=lambda pair: _key(*pair))[1]


def target_reached(approved_atom_count: int, target_atom_max: int) -> bool:
    """Q15：已通过原子数达标 → 停止自动拓展（手动追加批次不受限）。"""
    return approved_atom_count >= target_atom_max


# ---------- Q86：embedding 向量相似度与同义簇（Q16/Q19 的向量实现化） ----------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        raise ValueError("embedding vectors must be non-empty and of equal length")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def max_affinity(vector: list[float], basis: list[list[float]]) -> float | None:
    """Q16：与同维度已批准原子的最大余弦；无比较基时给 None（不凑 0 分）。"""
    if not basis:
        return None
    return round(max(cosine_similarity(vector, other) for other in basis), 6)


def assign_clusters(
    vectors: list[list[float]],
    line: float | None = None,
    *,
    labels: list | None = None,
) -> list[str | None]:
    """Q19：批内余弦 ≥ 成簇线者并查集聚成同义簇，返回每条的 cluster_id。

    labels 给定时仅在同 label 之间连边（Q86：只在同一选中维度内成簇，
    与同维度 affinity 基口径一致）；仅 ≥2 条的连通成分分配 cluster_id
    （uuid4），单条为 None。
    """
    threshold = cluster_line() if line is None else line
    n = len(vectors)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if labels is not None and labels[i] != labels[j]:
                continue
            if cosine_similarity(vectors[i], vectors[j]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    cluster_ids: dict[int, str] = {
        root: str(uuid.uuid4()) for root, members in groups.items() if len(members) >= 2
    }
    return [cluster_ids.get(find(i)) for i in range(n)]
