"""P4 切片（Q121/Q59）：段12 CONTENT-COMPLIANCE 复检第②项「语义级检测」。

复检四项（Q59）：词库扫描 + 语义级检测 + 施工指令核对 + 国家规则核对；
Q116 仅落词库扫描，Q121 落第②项（模型网关第 9 场景 ARTICLE-SEMANTIC-CHECK，
与 ARTICLE-QC 同构的只读 LLM 检测）。

Q121 定稿（02 C1.65，负责人拍板「纯 advisory」）：
- 语义发现落 ``review_hits["semantic"]``，供客户审阅 / 运营清洗参考；
- 不自动发证 / 驳回、不阻断 approve、不改动词库 ban 的 ``block_required``
  硬阻断（与 Q57 质量分降级、Q66「AI 不持审批 / 否决角色」一致）；
- 场景未配置 / 模型不可用 / 上游错误 / 输出非法时不阻断生成：
  semantic 段记 ``checked=false`` + ``error``，成品照常进 review。

施工指令核对、国家规则核对两项仍占位【原文未给出，待补】。
检测维度 code（unsubstantiated_claim / absolute_guarantee /
off_material_exaggeration / misleading_ambiguity）为 v0.1 工程口径，待业务方校准。
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import ContentProduct
from app.core.audit import append_audit
from app.core.model_registry import gateway
from app.core.model_registry.gateway import (
    GenerationUpstreamError,
    ModelConfigError,
    ModelUnavailable,
)
from app.core.model_registry.seeds import SCENE_ARTICLE_SEMANTIC
from app.core.skill7.models import SkillRun

SYSTEM_ACTOR_ID = "system:llm-gateway"
WF_10 = "WF-10"


def parse_semantic_output(text: str) -> tuple[list[dict], str | None]:
    """把模型输出解析为 ``(findings, error)``；非法形态降级为 ``([], error_code)``。

    - 必须是 JSON 对象且 ``findings`` 为数组，否则归一为空列表 + 错误码；
    - 每项必须是对象且含非空字符串 ``code``，否则跳过该项（容错不整体失败）；
    - ``message`` / ``excerpt`` 若给必须是字符串，否则丢弃该字段。
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [], "invalid_json"
    if not isinstance(data, dict):
        return [], "not_object"
    findings = data.get("findings")
    if not isinstance(findings, list):
        return [], "findings_not_array"
    cleaned: list[dict] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if not isinstance(code, str) or not code.strip():
            continue
        kept: dict = {"code": code.strip()}
        for field in ("message", "excerpt"):
            value = item.get(field)
            if isinstance(value, str):
                kept[field] = value
        cleaned.append(kept)
    return cleaned, None


async def run_semantic_check(
    session: AsyncSession, content: ContentProduct
) -> dict:
    """对已写 body 的成品跑语义复检，返回 ``review_hits["semantic"]`` 段（advisory）。"""
    variables = {
        "body": content.body or "",
        "language": content.language,
        "_final_id": content.final_id,
        "_goal": content.goal,
    }
    try:
        invocation = await gateway.invoke(session, SCENE_ARTICLE_SEMANTIC, variables)
    except (ModelConfigError, ModelUnavailable, GenerationUpstreamError) as exc:
        # 语义复检为辅助参考：模型不可用不阻断内容生成，记原因后照常进审阅。
        await append_audit(
            session,
            tenant_id=content.tenant_id,
            actor_id=SYSTEM_ACTOR_ID,
            actor_roles=[],
            action="content.semantic_unavailable",
            entity_type="content_product",
            entity_id=content.content_id,
            detail={"final_id": content.final_id, "reason": type(exc).__name__},
        )
        return {"checked": False, "findings": [], "error": type(exc).__name__}

    findings, error = parse_semantic_output(invocation.text)
    session.add(
        SkillRun(
            skill_id=SCENE_ARTICLE_SEMANTIC,
            wf_id=WF_10,
            tenant_id=content.tenant_id,
            product_space_id=content.product_space_id,
            status="succeeded",
            source="llm_auto",
            input_payload={
                "final_id": content.final_id,
                "kind": content.kind,
                "language": content.language,
            },
            output_payload={"findings": findings, "parse_error": error},
            input_tokens=invocation.input_tokens,
            output_tokens=invocation.output_tokens,
            model_id=invocation.model_id,
            input_cost=invocation.input_cost,
            output_cost=invocation.output_cost,
            currency_code=invocation.currency_code,
            created_by=SYSTEM_ACTOR_ID,
        )
    )
    await append_audit(
        session,
        tenant_id=content.tenant_id,
        actor_id=SYSTEM_ACTOR_ID,
        actor_roles=[],
        action="content.semantic_checked",
        entity_type="content_product",
        entity_id=content.content_id,
        detail={
            "final_id": content.final_id,
            "findings": len(findings),
            "model_id": invocation.model_id,
            **({"parse_error": error} if error else {}),
        },
    )
    segment: dict = {"checked": True, "findings": findings}
    if error:
        segment["error"] = error
    return segment
