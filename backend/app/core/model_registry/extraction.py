"""Q82 试点：CAT-RECOG 信号提取的进程内 LLM 调用编排。

形态（Q82-1/2）：operations 触发 → 取资料/启用信号/候选类目 → 进程内同步调
模型网关 → 解析校验为 C1RecognitionRequest 去 actor 形态 → 经 skill7 同一条
投递通道落 pending_review；Q1 三分支机械逻辑只在人工 confirm 后由适配器执行。
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.model_registry import gateway
from app.core.model_registry.seeds import SCENE_CAT_RECOG
from app.core.rbac import OPERATIONS, require_any_role
from app.core.skill7.schemas import CandidateInput, DeliverRunRequest
from app.core.skill7.service import deliver_generated_run
from app.product.modeling.models import C1SignalWeight, G1Category
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import ProductIntakeApplication

SYSTEM_ACTOR = Actor(id="system:llm-gateway", roles=[])


class RecognitionInvokeNotFound(Exception):
    pass


class RecognitionInvokeState(Exception):
    pass


class ExtractionOutputInvalid(Exception):
    pass


async def invoke_c1_recognition(
    session: AsyncSession, intake_id: str, trigger_actor: Actor
):
    require_any_role(trigger_actor, OPERATIONS)
    intake = await session.get(ProductIntakeApplication, intake_id)
    if intake is None:
        raise RecognitionInvokeNotFound(f"intake {intake_id} not found")
    if intake.status != sm.AI_RECOGNIZING:
        raise RecognitionInvokeState(
            f"LLM recognition only allowed in {sm.AI_RECOGNIZING}, current {intake.status}"
        )

    weights = (await session.scalars(
        select(C1SignalWeight).where(C1SignalWeight.enabled.is_(True))
    )).all()
    signal_keys = [w.signal for w in weights]
    if not signal_keys:
        raise gateway.ModelConfigError("no enabled c1 signal weights configured")

    categories = (await session.scalars(
        select(G1Category).where(G1Category.status == "active")
    )).all()
    category_options = [{"category_id": c.category_id, "name": c.name} for c in categories]

    profile = intake.profile or {}
    variables = {
        # 模板渲染用（字符串）：
        "product_profile": json.dumps(profile, ensure_ascii=False, indent=2),
        "signal_keys": "\n".join(f"- {key}" for key in signal_keys),
        "category_options": "\n".join(
            f"- {opt['category_id']} {opt['name']}" for opt in category_options
        )
        or "（无可用类目，candidates 给空数组）",
        # 合成替身驱动用（机读），不进模板占位：
        "_profile": profile,
        "_signal_keys": signal_keys,
        "_category_options": category_options,
    }

    invocation = await gateway.invoke(session, SCENE_CAT_RECOG, variables)
    try:
        parsed = json.loads(invocation.text)
        signals = parsed["signals"]
        raw_candidates = parsed.get("candidates", [])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ExtractionOutputInvalid(f"model output is not a valid recognition JSON: {exc}") from exc

    if not isinstance(signals, dict) or not signals:
        raise ExtractionOutputInvalid("model output signals must be a non-empty object")
    unknown = set(signals) - set(signal_keys)
    if unknown:
        raise ExtractionOutputInvalid(f"model output contains unknown signal keys: {sorted(unknown)}")
    try:
        signals = {key: float(value) for key, value in signals.items()}
    except (TypeError, ValueError) as exc:
        raise ExtractionOutputInvalid("signal scores must be numbers") from exc
    if not all(0.0 <= value <= 1.0 for value in signals.values()):
        raise ExtractionOutputInvalid("signal scores must be within 0..1")

    option_ids = {opt["category_id"] for opt in category_options}
    candidates = []
    for item in raw_candidates:
        cid = item.get("category_id")
        conf = item.get("conf")
        if cid not in option_ids:
            raise ExtractionOutputInvalid(f"candidate {cid!r} is not an active category option")
        if not isinstance(conf, (int, float)) or not 0.0 <= float(conf) <= 1.0:
            raise ExtractionOutputInvalid("candidate conf must be 0..1")
        candidates.append({"category_id": cid, "conf": float(conf)})

    payload: dict = {"signals": signals, "candidates": candidates}
    if isinstance(parsed.get("industry"), str) and parsed["industry"]:
        payload["industry"] = parsed["industry"]

    body = DeliverRunRequest(
        skill_id=SCENE_CAT_RECOG,
        intake_id=intake_id,
        input={"profile_fields": sorted(profile.keys()), "category_options": len(category_options)},
        output=payload,
        candidates=[CandidateInput(target_type="c1_recognition", payload=payload)],
        confidence=max((c["conf"] for c in candidates), default=None),
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
