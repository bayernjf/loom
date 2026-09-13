"""段3 字段池规划纯逻辑（无 DB/HTTP 依赖）。

依据：PT-FP-PLAN-V2.0（docs/06 §2.1）、Q8/Q9/Q10/Q11/Q12/Q15、line 14081/14133。
AI 不在本模块：WF-02（FIELDPOOL-PLAN→DIM-SOURCE→DIM-MERGE）候选由 M10 接入，
M3 接收结构化维度候选后做确定性的结构校验、越界处置与细看/疑似重复标记。

拍板值暂为常量，M10 迁配置中心（02 §C2 已登记 0.85 细看线/3-8 维度/0.9 重复线）。
"""

from dataclasses import dataclass, field

DIM_MIN = 3
DIM_MAX = 8
DETAIL_CONF_LINE = 0.85  # Q9：第一期全部走 Gate，低于此线仅标"需细看"
DUP_SIMILARITY_LINE = 0.9  # Q10：AI 标疑似重复，人工 Gate 终裁
TARGET_ATOM_MIN_DEFAULT = 15  # Q15
TARGET_ATOM_MAX_DEFAULT = 30

ROLE_PRODUCT_ATTRIBUTE = "product_attribute"
ROLE_RISK_CONTROL = "risk_control"
DIMENSION_ROLES = frozenset({ROLE_PRODUCT_ATTRIBUTE, ROLE_RISK_CONTROL})

GATE_PENDING = "pending_gate"
GATE_APPROVED = "approved"
GATE_REJECTED = "rejected"

DIM_SELECTED = "selected"
DIM_BACKUP = "backup"

ROLE_PRODUCT_REVIEWER = "product_reviewer"  # 字段池 Gate（docs/06 §4）
ROLE_DICTIONARY_ADMIN = "dictionary_admin"  # Q13 新字段转正

VIOL_BELOW_MIN = "below_min"
VIOL_MISSING_PRODUCT_ATTRIBUTE = "missing_product_attribute"
VIOL_MISSING_RISK_CONTROL = "missing_risk_control"
VIOL_MISSING_EVIDENCE = "missing_evidence"
VIOL_UNKNOWN_ROUTE = "unknown_route"
VIOL_UNKNOWN_ROLE = "unknown_role"
VIOL_ILLEGAL_FID = "illegal_fid"


@dataclass
class DimInput:
    field_name: str
    role: str
    source_route: str
    confidence: float
    # line 14081 红线：依据来源必须标明（用户输入片段/灵感库条目 id/规则名等）。
    source_ref: str | None = None
    # 持既有 G2 fid 走复用；为空表示新字段，落 g2_field_candidates（Q68）。
    fid: str | None = None
    # Q10：AI 给的相似度与指向项；≥0.9 仅标记，合并由人工终裁。
    similarity: float | None = None
    related_fid: str | None = None
    definition: str | None = None


@dataclass
class EvaluatedDim:
    dim: DimInput
    needs_detail: bool
    dup: bool


@dataclass
class PlanEvaluation:
    selected: list[EvaluatedDim] = field(default_factory=list)
    backup: list[EvaluatedDim] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def compliant(self) -> bool:
        return not self.violations


def _mark(dim: DimInput) -> EvaluatedDim:
    return EvaluatedDim(
        dim=dim,
        needs_detail=dim.confidence < DETAIL_CONF_LINE,
        dup=dim.similarity is not None and dim.similarity >= DUP_SIMILARITY_LINE,
    )


def evaluate_plan(
    dims: list[DimInput],
    *,
    sensitive: bool,
    enabled_routes: frozenset[str],
    active_fids: frozenset[str],
) -> PlanEvaluation:
    """对 WF-02 维度候选执行 PT-FP-PLAN 结构校验与 Q12 越界处置。

    - 未知角色/停用来源/缺依据/非法 fid：逐条记违规；
    - Q12：>8 按 confidence 降序留 Top8，余者入备选档（不删，可捞回）；
    - <3 不自动补，记 below_min 转人工；
    - product_attribute 恒 ≥1；risk_control 仅敏感行业强制（Q11）。
    """
    result = PlanEvaluation()
    marked = [_mark(d) for d in dims]

    for item in marked:
        d = item.dim
        if d.role not in DIMENSION_ROLES:
            result.violations.append(VIOL_UNKNOWN_ROLE)
        if d.source_route not in enabled_routes:
            result.violations.append(VIOL_UNKNOWN_ROUTE)
        if not (d.source_ref or "").strip():
            result.violations.append(VIOL_MISSING_EVIDENCE)
        if d.fid is not None and d.fid not in active_fids:
            result.violations.append(VIOL_ILLEGAL_FID)

    ordered = sorted(marked, key=lambda x: x.dim.confidence, reverse=True)
    result.selected = ordered[:DIM_MAX]
    result.backup = ordered[DIM_MAX:]

    roles = {x.dim.role for x in result.selected}
    if ROLE_PRODUCT_ATTRIBUTE not in roles:
        result.violations.append(VIOL_MISSING_PRODUCT_ATTRIBUTE)
    if sensitive and ROLE_RISK_CONTROL not in roles:
        result.violations.append(VIOL_MISSING_RISK_CONTROL)
    if len(result.selected) < DIM_MIN:
        result.violations.append(VIOL_BELOW_MIN)

    return result
