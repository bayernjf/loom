"""Q84 切片：C7 Layer4 新字段生成（TYPE-MATCH）的进程内 LLM 调用编排。

形态沿用 Q82/Q83（extraction.py / pwc_build.py）：operations 在业务端点显式
触发，给出已识别类目与必填 fid → 组装 L1/L2/L3 现状（有界变量）→ 进程内同步
调模型网关 → 严格校验为去 actor 的 C7ResolveRequest 形态（回显 category_id/
required_fids 必须与触发输入一致；模型回带的 confidence/score/fid/source_route
等一律剥离，Q84-3）→ 整请求单候选（c7_layer4，intake 锚点）经 skill7 同一条
投递通道落 pending_review。Q6/Q68 四层兜底与 Q13 dictionary_admin 转正 Gate
只在 operations 人工 confirm 后由既有适配器 resolve_c7 执行，本模块一项不绕。
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.model_registry import gateway
from app.core.model_registry.schemas import C7ResolveInvokeRequest
from app.core.model_registry.seeds import SCENE_TYPE_MATCH
from app.core.rbac import OPERATIONS, require_any_role
from app.core.skill7.schemas import CandidateInput, DeliverRunRequest
from app.core.skill7.service import deliver_generated_run
from app.product.modeling import c7
from app.product.modeling.models import G1Category, G1CategoryTemplate
from app.product.modeling.service import CategoryNotFound
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import G2Field, ProductIntakeApplication

SYSTEM_ACTOR = Actor(id="system:llm-gateway", roles=[])


class C7ResolveInvokeNotFound(Exception):
    pass


class C7ResolveInvokeState(Exception):
    pass


class C7ResolveOutputInvalid(Exception):
    pass


async def invoke_c7_resolve(
    session: AsyncSession,
    intake_id: str,
    body: C7ResolveInvokeRequest,
    trigger_actor: Actor,
):
    require_any_role(trigger_actor, OPERATIONS)

    intake = await session.get(ProductIntakeApplication, intake_id)
    if intake is None:
        raise C7ResolveInvokeNotFound(f"intake {intake_id} not found")
    if intake.status != sm.AI_RECOGNIZING:
        # TYPE-MATCH 是 WF-01 在 ai_recognizing 内的步骤（与 CAT-RECOG 同档，Q84 实现补登）。
        raise C7ResolveInvokeState(
            f"LLM C7 resolve only allowed in {sm.AI_RECOGNIZING}, current {intake.status}"
        )

    category = await session.get(G1Category, body.category_id)
    if category is None:
        raise CategoryNotFound(body.category_id)
    if category.status != "active":
        raise C7ResolveInvokeState(
            f"category {body.category_id} is {category.status}, only active category is resolvable"
        )

    required_fids = list(dict.fromkeys(body.required_fids))
    c7.validate_fids(required_fids)  # Q68：空串/'-' 在调模型前就拦（422）。

    own = await session.get(G1CategoryTemplate, body.category_id)
    own_fields = list(own.field_list) if own is not None and own.status == "approved" else []

    sibling_count = (
        await session.scalar(
            select(G1Category.category_id)
            .join(G1CategoryTemplate, G1CategoryTemplate.category_id == G1Category.category_id)
            .where(
                G1Category.parent_id == category.parent_id,
                G1Category.category_id != body.category_id,
                G1CategoryTemplate.status == "approved",
            )
            .order_by(G1Category.product_count.desc())
            .limit(1)
        )
    )
    approved_sibling_count = 1 if sibling_count is not None else 0

    active_rows = (
        await session.execute(
            select(G2Field.fid, G2Field.field_name).where(G2Field.status == "active")
        )
    ).all()
    active_fids = [row[0] for row in active_rows]
    floor = c7.layer3_coverage_floor()
    ratio = c7.coverage(required_fids, active_fids)
    matched = [fid for fid in required_fids if fid in set(active_fids)]
    missing = [fid for fid in required_fids if fid not in set(active_fids)]
    name_of = {row[0]: row[1] for row in active_rows}

    variables = {
        # 模板渲染用（字符串）：
        "category": f"- {category.category_id} | {category.name}",
        "required_fids": "\n".join(f"- {fid}" for fid in required_fids) or "（无）",
        "own_template": ", ".join(own_fields) if own_fields else "（无 approved 模板）",
        "sibling_summary": (
            f"{approved_sibling_count} 个 approved 兄弟模板"
            if approved_sibling_count
            else "0（无 approved 兄弟模板）"
        ),
        "coverage_floor": str(floor),
        "g2_coverage": (
            f"覆盖率 {ratio}（matched={matched or '无'}；未覆盖={missing or '无'}）\n"
            "active G2 字段：\n"
            + "\n".join(f"- {fid} | {name_of[fid]}" for fid in active_fids)
        ),
        # 合成替身驱动用（机读），不进模板占位：
        "_category_id": category.category_id,
        "_required_fids": required_fids,
        "_active_fids": active_fids,
    }

    invocation = await gateway.invoke(session, SCENE_TYPE_MATCH, variables)
    try:
        parsed = json.loads(invocation.text)
        raw_category = parsed["category_id"]
        raw_required = parsed["required_fids"]
        raw_proposals = parsed["l4_proposals"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise C7ResolveOutputInvalid(
            f"model output is not a valid C7 resolve JSON: {exc}"
        ) from exc

    if raw_category != category.category_id:
        raise C7ResolveOutputInvalid(
            f"model output category_id {raw_category!r} differs from triggered category"
        )
    if not isinstance(raw_required, list) or any(not isinstance(f, str) for f in raw_required):
        raise C7ResolveOutputInvalid("model output required_fids must be a list of strings")
    if set(raw_required) != set(required_fids):
        # 必填位由触发输入给定，模型不得增删（有界输入/输出，Q84-3）。
        raise C7ResolveOutputInvalid(
            "model output required_fids must echo the triggered required_fids exactly"
        )
    if not isinstance(raw_proposals, list):
        raise C7ResolveOutputInvalid("model output l4_proposals must be a list")

    proposals: list[dict] = []
    seen_names: set[str] = set()
    for item in raw_proposals:
        if not isinstance(item, dict):
            raise C7ResolveOutputInvalid("each l4 proposal must be an object")
        field_name = item.get("field_name")
        if not isinstance(field_name, str) or not field_name.strip():
            raise C7ResolveOutputInvalid("each l4 proposal requires a non-empty field_name")
        if item.get("fid") == c7.FORBIDDEN_FID:
            raise C7ResolveOutputInvalid("l4 proposal must not carry fid:'-' (Q68)")
        if field_name in seen_names:
            raise C7ResolveOutputInvalid(f"duplicate l4 proposal field_name: {field_name}")
        seen_names.add(field_name)
        # 只透传 field_name/definition；confidence/score/fid/source_route 等一律不透传
        # （Q84-3：新字段不打模型置信分；source_route 枚举原文未给，v0.1 不接模型值）。
        proposal = {"field_name": field_name}
        definition = item.get("definition")
        if isinstance(definition, str) and definition.strip():
            proposal["definition"] = definition
        proposals.append(proposal)

    payload = {
        "category_id": category.category_id,
        "required_fids": required_fids,
        "l4_proposals": proposals,
    }
    body = DeliverRunRequest(
        skill_id=SCENE_TYPE_MATCH,
        intake_id=intake_id,
        input={
            "category_id": category.category_id,
            "required_fid_count": len(required_fids),
            "l3_coverage": ratio,
            "l3_floor": floor,
            "approved_sibling_count": approved_sibling_count,
        },
        output=payload,
        candidates=[CandidateInput(target_type="c7_layer4", payload=payload)],
        input_tokens=invocation.input_tokens,
        output_tokens=invocation.output_tokens,
        actor=SYSTEM_ACTOR,
    )
    return await deliver_generated_run(
        session,
        body,
        model_id=invocation.model_id,
        input_cost=invocation.input_cost,
        output_cost=invocation.output_cost,
        currency_code=invocation.currency_code,
    )
