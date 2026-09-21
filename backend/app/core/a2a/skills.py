"""Plan 模式 skill 执行器（Q150）：纯函数，无 DB、无 LLM、无链路副作用。"""

from __future__ import annotations

_SKILL_PLANS: dict[str, dict] = {
    "generate-content": {
        "required": ["tenant_id", "product_id"],
        "steps": [
            "定位租户与产品的 ContentSpace 与目标语言（段 12 多语言口径）",
            "按三包（策略/结构/表达）规划候选生成批次",
            "列出将经过的人工 Gate（QC 阈值 0.85 / 语义检测均为 advisory）",
            "给出 final_id 组装前的完整前置条件清单",
        ],
    },
    "compliance-check": {
        "required": ["tenant_id", "content_id"],
        "steps": [
            "定位成品与其发布位 PCP 约束",
            "规划合规清洗检查项（词表 + 平台规则）",
            "标注哪些结果为 advisory、哪些由人工 Gate 裁决",
        ],
    },
    "effect-backfill": {
        "required": ["tenant_id", "content_id"],
        "steps": [
            "按 Q128 客户通道语义规划 records 批次（同租户、非 discarded 成品）",
            "列出幂等与整批 all-or-nothing 约束的核对点",
            "规划孤儿/认领路径（仅当 external_content_id 无法精确匹配时提示）",
        ],
    },
}


def list_skill_ids() -> list[str]:
    return list(_SKILL_PLANS)


def run_plan_skill(skill_id: str, params: dict) -> dict:
    """返回 plan 结果 dict：state ∈ completed | input-required | failed。"""
    plan = _SKILL_PLANS.get(skill_id)
    if plan is None:
        return {
            "state": "failed",
            "message": f"unknown skill: {skill_id}; available: {', '.join(_SKILL_PLANS)}",
        }
    missing = [key for key in plan["required"] if not params.get(key)]
    if missing:
        return {
            "state": "input-required",
            "message": f"missing required parameters: {', '.join(missing)}",
        }
    return {
        "state": "completed",
        "name": f"{skill_id}-plan",
        "params": params,
        "steps": plan["steps"],
        "summary": f"{skill_id}: plan generated for tenant={params['tenant_id']}.",
    }
