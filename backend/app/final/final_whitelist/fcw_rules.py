"""PT-FCW-ASM-V1.0 机械规则（段11，06 §2.6 + Q52/Q53/Q54）。

纯函数、不落库、不做 IO：服务层负责解析六路材料，本模块只做
7 项 Guard 机械核验与 Q54 临时评分（仅排序、永不做门槛）。
"""

from dataclasses import dataclass, field

from app.core.config_center.knobs import knob


# Q54 一期临时权重（line 135；待段13 回流校准），经配置中心热更（M10c 接入）。
def w_pwc_skeleton() -> float:
    return knob("fcw.w_pwc_skeleton")


def w_slot_fit() -> float:
    return knob("fcw.w_slot_fit")


def w_package_conf() -> float:
    return knob("fcw.w_package_conf")

PWS_FROZEN = "frozen"
PCP_ACTIVE = "active"
PACKAGE_ACTIVE = "active"
GATE_APPROVED = "approved"

G1 = "g1_pws_frozen"
G2 = "g2_compliance_clear"
G3 = "g3_packages_active"
G4 = "g4_product_space_consistent"
G5 = "g5_tenant_consistent"
G6 = "g6_law_review"
G7 = "g7_pws_active_version"


@dataclass
class Gate:
    """M7 gate_view 的机械视图（ccr/service.gate_view）。"""

    latest_report_id: str | None
    report_status: str | None
    block_required: bool
    cleaning_passed: bool
    law_review_required: bool
    law_review_status: str | None
    law_review_passed: bool


@dataclass
class MaterialRef:
    """一份配置实例的归属与状态（PCP/CSP/CSTP/CEP 通用）。"""

    ref_id: str
    product_space_id: str
    tenant_id: str
    status: str
    gate: str = GATE_APPROVED


@dataclass
class Materials:
    """组装一次 FCW 所需六路材料（服务层解析后传入）。"""

    pws_id: str
    pws_status: str
    pws_is_active: bool
    pws_product_space_id: str
    pws_tenant_id: str
    gate: Gate
    pcp: MaterialRef
    csp: MaterialRef
    cstp: MaterialRef
    cep: MaterialRef
    request_product_space_id: str


@dataclass
class GuardResult:
    code: str
    passed: bool
    detail: dict = field(default_factory=dict)


def evaluate_guards(m: Materials) -> list[GuardResult]:
    """Q52/Q53 七项机械核验。逐项求值、不因前项失败短路（审计要完整结果）。"""
    results: list[GuardResult] = []

    results.append(
        GuardResult(
            G1,
            m.pws_status == PWS_FROZEN,
            {"pws_status": m.pws_status, "required": PWS_FROZEN},
        )
    )

    # ② block_required=false（line 2071）。【实现补】无清洗报告时 gate_view 的
    # block_required 默认 False——为不使"未清洗"伪装成放行，同时要求
    # cleaning_passed=true（报告状态 clean/approved）；语义=合规已放行。
    results.append(
        GuardResult(
            G2,
            (not m.gate.block_required) and m.gate.cleaning_passed,
            {
                "latest_report_id": m.gate.latest_report_id,
                "report_status": m.gate.report_status,
                "block_required": m.gate.block_required,
                "cleaning_passed": m.gate.cleaning_passed,
            },
        )
    )

    packages_ok = (
        m.pcp.status == PCP_ACTIVE
        and m.csp.status == PACKAGE_ACTIVE
        and m.cstp.status == PACKAGE_ACTIVE
        and m.cep.status == PACKAGE_ACTIVE
        and m.csp.gate == GATE_APPROVED
        and m.cstp.gate == GATE_APPROVED
        and m.cep.gate == GATE_APPROVED
    )
    results.append(
        GuardResult(
            G3,
            packages_ok,
            {
                "pcp": {"id": m.pcp.ref_id, "status": m.pcp.status},
                "csp": {"id": m.csp.ref_id, "status": m.csp.status, "gate": m.csp.gate},
                "cstp": {
                    "id": m.cstp.ref_id,
                    "status": m.cstp.status,
                    "gate": m.cstp.gate,
                },
                "cep": {"id": m.cep.ref_id, "status": m.cep.status, "gate": m.cep.gate},
            },
        )
    )

    ps_ids = {
        "pws": m.pws_product_space_id,
        "pcp": m.pcp.product_space_id,
        "csp": m.csp.product_space_id,
        "cstp": m.cstp.product_space_id,
        "cep": m.cep.product_space_id,
    }
    results.append(
        GuardResult(
            G4,
            all(v == m.request_product_space_id for v in ps_ids.values()),
            {"product_space_ids": ps_ids, "request": m.request_product_space_id},
        )
    )

    tenant_ids = {
        "pws": m.pws_tenant_id,
        "pcp": m.pcp.tenant_id,
        "csp": m.csp.tenant_id,
        "cstp": m.cstp.tenant_id,
        "cep": m.cep.tenant_id,
    }
    tenant = m.pws_tenant_id
    results.append(
        GuardResult(
            G5,
            all(v == tenant for v in tenant_ids.values()),
            {"tenant_ids": tenant_ids},
        )
    )

    # ⑥ 仅在法审被触发时要求 approved（Q49/Q53：未触发法审不阻断）。
    law_ok = (not m.gate.law_review_required) or m.gate.law_review_passed
    results.append(
        GuardResult(
            G6,
            law_ok,
            {
                "law_review_required": m.gate.law_review_required,
                "law_review_status": m.gate.law_review_status,
                "law_review_passed": m.gate.law_review_passed,
            },
        )
    )

    results.append(
        GuardResult(
            G7,
            m.pws_is_active and m.pws_status == PWS_FROZEN,
            {"pws_is_active": m.pws_is_active, "pws_status": m.pws_status},
        )
    )
    return results


def guards_passed(results: list[GuardResult]) -> bool:
    return all(r.passed for r in results)


@dataclass
class ScoreOutcome:
    """Q54 评分结果：分仅用于排序，绝不当 Guard/门槛。"""

    score: float | None
    incomplete: bool
    detail: dict


def score_fcw(
    *,
    pwc_score: float | None,
    slot_fit_score: float | None,
    package_confs: list[float | None],
    w_pwc: float | None = None,
    w_fit: float | None = None,
    w_conf: float | None = None,
) -> ScoreOutcome:
    """Q54：骨架分×0.4 + 发布位 fit×0.3 + 三包 conf 均值×0.3。

    尺度统一到 0-100：PWC 分与 conf 为 0-1（M5/Q47），fit_score 为 0-100（Q34）。
    任一来源缺失 → 不出分、incomplete=true（不凑分，对齐 Q22b；
    分仅排序，缺失不影响发证）。权重缺省取配置中心（显式传值覆盖，便于测试）。
    """
    if w_pwc is None:
        w_pwc = w_pwc_skeleton()
    if w_fit is None:
        w_fit = w_slot_fit()
    if w_conf is None:
        w_conf = w_package_conf()
    confs = [c for c in package_confs if c is not None]
    missing: list[str] = []
    if pwc_score is None:
        missing.append("pwc_score")
    if slot_fit_score is None:
        missing.append("slot_fit_score")
    if len(confs) != len(package_confs):
        missing.append("package_conf")

    detail = {
        "formula": "pwc*0.4 + fit*0.3 + conf_avg*0.3",
        "weights": {"pwc": w_pwc, "fit": w_fit, "conf": w_conf},
        "raw": {
            "pwc_score": pwc_score,
            "slot_fit_score": slot_fit_score,
            "package_confs": package_confs,
        },
    }
    if missing:
        detail["missing"] = missing
        return ScoreOutcome(None, True, detail)

    conf_avg = sum(confs) / len(confs)
    score = pwc_score * 100 * w_pwc + slot_fit_score * w_fit + conf_avg * 100 * w_conf
    detail["scaled"] = {
        "pwc_x100": pwc_score * 100,
        "conf_avg_x100": conf_avg * 100,
    }
    detail["score"] = score
    return ScoreOutcome(score, False, detail)
