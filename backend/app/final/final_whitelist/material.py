"""Q155 台内白名单卡片「6 层提示词原料包」JSON 导出（docs/09:87，01 line 2745）。

口径分界（Q100/Q132/Q142 三处定论）：中台 ``/api/exports/fcw.*`` 严格只导
final_id 单列；**6 层原料包属台内卡片详情/复制口径，是另一个面**，由本模块按
单条 final_id 反解析发证时引用的 6 路不可变/版本化材料：

    final_id = 产品 PWS（私域原子）+ 平台 PCP + 策略 CSP
             + 结构 CSTP + 表达 CEP + 合规 CCR（01 line 14/2745）

只读、零迁移、不触发 Guard、不写审计（同 GET /api/fcw/{final_id} 读路径纪律）。
产品层直接取 PWS 冻结快照（不可变，已含 atoms/pwcs 全量）；骨架 PWC 以
fcw.pwc_id 在快照 pwcs 中标注。任一引用行物理缺失（正常不发生，均为状态机
软删）不致 500，该层回 ``{"_ref": id, "available": false}`` 并收 warning。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision.compliance_center.models import CcrReport, LawReview
from app.decision.layer_strategy.models import Package
from app.final.final_whitelist.models import FinalContentWhitelist
from app.platform.platform_adaptation.models import PcpWeightTable, PublishSlot
from app.product.whitelist_center.models import PwsSnapshot

MATERIAL_SCHEMA = "loom.fcw.material-pack.v1"


def _ref_missing(ref_id: str | None) -> dict:
    return {"_ref": ref_id, "available": False}


async def build_material_pack(
    session: AsyncSession, fcw: FinalContentWhitelist
) -> dict:
    """按一条已发证 FCW 的 6 路 id 引用，反解析完整原料包（不做 IO 写、不校验状态）。"""

    warnings: list[str] = []

    # ---------- 产品层：PWS 不可变冻结快照（私域原子 + 骨架 PWC） ----------
    pws = await session.get(PwsSnapshot, fcw.pws_id)
    if pws is None:
        warnings.append(f"pws {fcw.pws_id} missing")
        product_layer = _ref_missing(fcw.pws_id)
    else:
        product_layer = {
            "pws_id": pws.pws_id,
            "version": pws.version,
            "status": pws.status,
            "is_active": pws.is_active,
            "fingerprint": pws.fingerprint,
            "pool_id": pws.pool_id,
            "created_at": pws.created_at,
            # 发证时消费的那份骨架 PWC（在冻结快照 pwcs 内标注）。
            "skeleton_pwc_id": fcw.pwc_id,
            # 冻结快照全量（pool_id/atoms[]/pwcs[]），不可变。
            "snapshot": pws.snapshot,
        }

    # ---------- 平台层：PCP 17 池权重 + 发证发布位档案 ----------
    pcp = await session.get(PcpWeightTable, fcw.pcp_id)
    slot = await session.get(PublishSlot, fcw.slot_id)
    if pcp is None:
        warnings.append(f"pcp {fcw.pcp_id} missing")
        platform_layer = _ref_missing(fcw.pcp_id)
    else:
        platform_layer = {
            "pcp_id": pcp.pcp_id,
            "template_code": pcp.template_code,
            "platform": pcp.platform,
            "weights": pcp.weights,
            "status": pcp.status,
            "slot": (
                {
                    "slot_id": slot.slot_id,
                    "platform": slot.platform,
                    "code": slot.code,
                    "name": slot.name,
                    "slot_type": slot.slot_type,
                    "chars_max": slot.chars_max,
                    "dur_min": slot.dur_min,
                    "dur_max": slot.dur_max,
                    "traffic": slot.traffic,
                    "safe": slot.safe,
                    "conv": slot.conv,
                    "load": slot.load,
                    "risk": slot.risk,
                    "source_url": slot.source_url,
                }
                if slot is not None
                else _ref_missing(fcw.slot_id)
            ),
        }
    if slot is None and pcp is not None:
        warnings.append(f"publish slot {fcw.slot_id} missing")

    # ---------- 策略/结构/表达三包（CSP/CSTP/CEP 配置实例） ----------
    package_ids = {
        "strategy": ("csp", fcw.csp_package_id),
        "structure": ("cstp", fcw.cstp_package_id),
        "expression": ("cep", fcw.cep_package_id),
    }
    package_layers: dict[str, dict] = {}
    for layer_name, (_kind, package_id) in package_ids.items():
        pkg = await session.get(Package, package_id)
        if pkg is None:
            warnings.append(f"{_kind} package {package_id} missing")
            package_layers[layer_name] = _ref_missing(package_id)
            continue
        package_layers[layer_name] = {
            "kind": pkg.kind,
            "package_id": pkg.package_id,
            "platform": pkg.platform,
            "goal": pkg.goal,
            "payload": pkg.payload,
            "conf": pkg.conf,
            "gate": pkg.gate,
            "status": pkg.status,
        }

    # ---------- 合规层：发证时 CCR 报告 + 该 PWS 下法审记录 ----------
    ccr = (
        await session.get(CcrReport, fcw.ccr_report_id)
        if fcw.ccr_report_id
        else None
    )
    if fcw.ccr_report_id and ccr is None:
        warnings.append(f"ccr report {fcw.ccr_report_id} missing")
    law_rows = (
        await session.scalars(
            select(LawReview)
            .where(LawReview.pws_id == fcw.pws_id)
            .order_by(LawReview.created_at)
        )
    ).all()
    compliance_layer = {
        "ccr_report_id": fcw.ccr_report_id,
        "report": (
            {
                "ccr_id": ccr.ccr_id,
                "status": ccr.status,
                "country": ccr.country,
                "block_required": ccr.block_required,
                "hits": ccr.hits,
                "wordlist_context": ccr.wordlist_context,
                "run_by": ccr.run_by,
                "decided_by": ccr.decided_by,
                "decided_at": ccr.decided_at,
                "created_at": ccr.created_at,
            }
            if ccr is not None
            else (_ref_missing(fcw.ccr_report_id) if fcw.ccr_report_id else None)
        ),
        "law_reviews": [
            {
                "law_review_id": row.law_review_id,
                "domain": row.domain,
                "status": row.status,
                "conclusion": row.conclusion,
                "decided_by": row.decided_by,
                "decided_at": row.decided_at,
                "created_at": row.created_at,
            }
            for row in law_rows
        ],
    }

    return {
        "schema": MATERIAL_SCHEMA,
        "final_id": fcw.final_id,
        "issued": {
            "tenant_id": fcw.tenant_id,
            "product_space_id": fcw.product_space_id,
            "platform": fcw.platform,
            "slot_id": fcw.slot_id,
            "goal": fcw.goal,
            "country": fcw.country,
            "score": fcw.score,
            "score_incomplete": fcw.score_incomplete,
            "score_detail": fcw.score_detail,
            "publish_status": fcw.publish_status,
            "issued_by": fcw.issued_by,
            "created_at": fcw.created_at,
            "published_at": fcw.published_at,
        },
        "layers": {
            "product": product_layer,
            "platform": platform_layer,
            "strategy": package_layers["strategy"],
            "structure": package_layers["structure"],
            "expression": package_layers["expression"],
            "compliance": compliance_layer,
        },
        "guards": fcw.guards,
        "warnings": warnings,
    }
