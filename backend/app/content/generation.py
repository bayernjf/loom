"""P4 切片 2：段12 文章生成（ARTICLE-GEN）的进程内 LLM 调用编排。

形态（Q116 定稿）：operations 在业务端点显式触发 → 只读组装 FCW 6 层原料 →
进程内同步调模型网关 → 严格校验为 {"body": str} → 直接写 content_products.body。
段12 的 Gate 是客户审阅（Q59），非运营审核，故不走 skill7 候选通道（Q66 的人工
Gate 在段12 即客户）；成本经 SkillRun 记录（Q67），writeAudit 留痕。
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import CONTENT_GENERATING, ContentProduct
from app.core.actor import Actor
from app.core.audit import append_audit
from app.core.model_registry import gateway
from app.core.model_registry.seeds import SCENE_ARTICLE_GEN
from app.core.rbac import OPERATIONS, require_any_role
from app.core.skill7.models import SkillRun
from app.decision.compliance_center.models import CcrReport
from app.decision.layer_strategy.models import Package
from app.final.final_whitelist.models import FinalContentWhitelist
from app.platform.platform_adaptation.models import PcpWeightTable
from app.product.whitelist_center.models import PwsSnapshot

SYSTEM_ACTOR = Actor(id="system:llm-gateway", roles=[])
WF_10 = "WF-10"


class ArticleGenFcwNotFound(Exception):
    pass


class ArticleGenState(Exception):
    pass


class ArticleGenOutputInvalid(Exception):
    pass


async def _assemble_materials(session: AsyncSession, fcw: FinalContentWhitelist) -> dict:
    """只读展开 FCW 6 层包 ID → 生成原料（PT-ART-GEN-V1.5：只读消费，不重决策）。"""
    atoms: list = []
    pws = await session.get(PwsSnapshot, fcw.pws_id)
    if pws is not None and pws.snapshot:
        atoms = pws.snapshot.get("atoms", [])

    packages: dict[str, dict] = {}
    for kind, pid in (
        ("csp", fcw.csp_package_id),
        ("cstp", fcw.cstp_package_id),
        ("cep", fcw.cep_package_id),
    ):
        pkg = await session.get(Package, pid)
        packages[kind] = dict(pkg.payload) if pkg is not None else {}

    weights: dict = {}
    pcp = await session.get(PcpWeightTable, fcw.pcp_id)
    if pcp is not None:
        weights = dict(pcp.weights)

    ccr_hits: dict = {}
    if fcw.ccr_report_id:
        report = await session.get(CcrReport, fcw.ccr_report_id)
        if report is not None:
            ccr_hits = dict(report.hits)

    return {
        "final_id": fcw.final_id,
        "goal": fcw.goal,
        "platform": fcw.platform,
        "country": fcw.country,
        "atoms": atoms,
        "packages": packages,
        "weights": weights,
        "ccr_hits": ccr_hits,
    }


def _materials_text(materials: dict) -> str:
    atoms = materials["atoms"] or []
    atom_text = " ".join(str(a.get("content", "")) for a in atoms) or "（无原子）"
    return (
        f"final_id={materials['final_id']}\n"
        f"goal={materials['goal']} platform={materials['platform']} "
        f"country={materials['country'] or '通用'}\n"
        f"产品原子：{atom_text}\n"
        f"三包：{json.dumps(materials['packages'], ensure_ascii=False)}\n"
        f"平台权重：{json.dumps(materials['weights'], ensure_ascii=False)}\n"
        f"合规命中：{json.dumps(materials['ccr_hits'], ensure_ascii=False)}"
    )


async def invoke_article_gen(
    session: AsyncSession,
    content: ContentProduct,
    trigger_actor: Actor,
) -> ContentProduct:
    """draft→generating 后调用：组装原料 → 调模型 → 写 body → 记 SkillRun。"""
    require_any_role(trigger_actor, OPERATIONS)
    if content.status != CONTENT_GENERATING:
        raise ArticleGenState(
            f"ARTICLE-GEN only allowed in {CONTENT_GENERATING}, current {content.status}"
        )

    fcw = await session.get(FinalContentWhitelist, content.final_id)
    if fcw is None:
        raise ArticleGenFcwNotFound(f"FCW {content.final_id} not found")

    materials = await _assemble_materials(session, fcw)
    variables = {
        "materials": _materials_text(materials),
        "language": content.language,
        "_final_id": content.final_id,
        "_goal": content.goal,
    }
    invocation = await gateway.invoke(session, SCENE_ARTICLE_GEN, variables)

    try:
        parsed = json.loads(invocation.text)
        body = parsed["body"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ArticleGenOutputInvalid(
            f"model output is not a valid ARTICLE-GEN JSON: {exc}"
        ) from exc
    if not isinstance(body, str):
        raise ArticleGenOutputInvalid("model output body must be a string")

    content.body = body

    # 成本记录（Q67）：段12 不走 skill7 候选，SkillRun 在此手动落（source=llm_auto）。
    session.add(
        SkillRun(
            skill_id=SCENE_ARTICLE_GEN,
            wf_id=WF_10,
            tenant_id=content.tenant_id,
            product_space_id=content.product_space_id,
            status="succeeded",
            source="llm_auto",
            input_payload={"final_id": content.final_id, "kind": content.kind, "language": content.language},
            output_payload={"body": body},
            input_tokens=invocation.input_tokens,
            output_tokens=invocation.output_tokens,
            model_id=invocation.model_id,
            input_cost=invocation.input_cost,
            output_cost=invocation.output_cost,
            currency_code=invocation.currency_code,
            created_by=SYSTEM_ACTOR.id,
        )
    )
    await append_audit(
        session,
        tenant_id=content.tenant_id,
        actor_id=SYSTEM_ACTOR.id,
        actor_roles=[],
        action="content.generated",
        entity_type="content_product",
        entity_id=content.content_id,
        detail={"final_id": content.final_id, "model_id": invocation.model_id},
    )
    return content
