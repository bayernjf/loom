"""P4 切片（Q120/Q57）：段12 AI 质量分（模型网关第 8 场景 ARTICLE-QC）。

定位（Q57，红旗 §B1.12 裁决）：质量分保留为流水线自动关卡但**降级为辅助参考**——
- 阈值 `content.ai_quality_threshold`（默认 0.85）配置化，仅用于界面提示「需细看」；
- 分数**不自动发证、也不自动驳回/阻断**（段12 的 Gate 仍是客户审阅 Q59）；
- 段13 回流后与真实互动数据校准（后置，本期不做）。

因此 ARTICLE-QC 是生成后的**只读评分**：模型/网关不可用或输出非法时不阻断内容生成，
质量分留空并记录 qc_error，成品照常进入客户审阅（review）。

Q56 止损（3 次仍 <0.85 转人工）不新增状态：重生成次数由 `content.regen_limit`（默认 3）
在 revise 入口卡住（超限只能 reject），低分成品在审阅页由人工转清洗区编辑或作废回池。
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
from app.core.model_registry.seeds import SCENE_ARTICLE_QC
from app.core.skill7.models import SkillRun

QUALITY_THRESHOLD_KEY = "content.ai_quality_threshold"
REGEN_LIMIT_KEY = "content.regen_limit"

SYSTEM_ACTOR_ID = "system:llm-gateway"
WF_10 = "WF-10"


def parse_qc_output(text: str) -> tuple[float | None, list]:
    """把 ARTICLE-QC 模型输出解析为 (score, issues)；任何非法形态降级为 (None, 错误明细)。

    - 必须是 JSON 对象且含 0..1 的数值 score（bool 不算数值）；
    - issues 必须是数组，否则归一为空数组；
    - score 缺失/越界/非数值时返回 None，并在 issues 记 qc_error（辅助参考不抛错）。
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, [{"qc_error": "invalid_json"}]
    if not isinstance(data, dict):
        return None, [{"qc_error": "not_object"}]
    score = data.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None, [{"qc_error": "score_not_number"}]
    score = float(score)
    if not 0.0 <= score <= 1.0:
        return None, [{"qc_error": "score_out_of_range"}]
    issues = data.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    return round(score, 4), issues


def quality_advisory_for(score: float | None, threshold: float) -> bool | None:
    """score 低于阈值 → True（界面提示需细看）；无分数（QC 不可用）→ None。"""
    if score is None:
        return None
    return score < threshold


async def invoke_article_qc(
    session: AsyncSession, content: ContentProduct
) -> ContentProduct:
    """对已写 body 的成品跑一次 ARTICLE-QC，落 quality_score/issues（advisory，不阻断）。"""
    variables = {
        "body": content.body or "",
        "language": content.language,
        "_final_id": content.final_id,
        "_goal": content.goal,
    }
    try:
        invocation = await gateway.invoke(session, SCENE_ARTICLE_QC, variables)
    except (ModelConfigError, ModelUnavailable, GenerationUpstreamError) as exc:
        # Q57 辅助参考：质检模型不可用不阻断内容生成，分数留空、记原因，照常进审阅。
        content.quality_score = None
        content.quality_issues = [{"qc_error": type(exc).__name__}]
        await append_audit(
            session,
            tenant_id=content.tenant_id,
            actor_id=SYSTEM_ACTOR_ID,
            actor_roles=[],
            action="content.quality_unavailable",
            entity_type="content_product",
            entity_id=content.content_id,
            detail={"final_id": content.final_id, "reason": type(exc).__name__},
        )
        return content

    score, issues = parse_qc_output(invocation.text)
    content.quality_score = score
    content.quality_issues = issues

    session.add(
        SkillRun(
            skill_id=SCENE_ARTICLE_QC,
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
            output_payload={"score": score, "issues": issues},
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
        action="content.quality_scored",
        entity_type="content_product",
        entity_id=content.content_id,
        detail={"final_id": content.final_id, "score": score, "model_id": invocation.model_id},
    )
    return content
