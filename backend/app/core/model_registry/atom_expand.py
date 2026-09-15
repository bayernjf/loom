"""Q86 切片：WF-03 原子批量补池（ATOM-EXPAND 生产契约）的两次模型调用编排。

形态沿用 Q82-Q85：operations 在业务端点显式触发 → 花 token 前先过预闸
（PS 存在 / 池存在且 approved / Q15 已达 target_atom_max 停拓，仅 AI 批次受限）
→ 构造有界变量（资料行、本池 selected 维度、各维已通过/冻结原子、目标区间、
敏感标、batch_size）→ 第一次调用 chat 场景 CONFLICT-PRECHECK（WF-03 唯一声明
produces_candidates 的步骤；Prompt 挂此 skill，内容是 ATOM-EXPAND 生产契约）
产出整批原子候选 → 第二次调用 embedding 场景 ATOM-AFFINITY（无 Prompt、不产
候选）对批内文本与同维已存向量做向量化 → affinity（Q16）与 cluster_id（Q19）
一律本地确定性计算，模型输出中的 affinity/cluster_id 直接剥离（同 Q83/Q84/Q85
剥离评分的纪律）；ai_risk 枚举校验后透传（Q17 AI 兜底档，词表强制仍只升不降）。

整批作为单个 atom_batch 候选（single_candidate）经 skill7 同一条投递通道落
pending_review；Q14/Q15/同批规范化去重/维度必选/line 11189 事实全局唯一/
Q17/line 840/Q18 缺证降级全部在既有 submit_batch 内执行，本模块一项不绕。
restock_auto 自动触发留给 M8 worker，本切片只接 operations 显式触发。
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.model_registry import gateway
from app.core.model_registry.schemas import AtomExpandInvokeRequest
from app.core.model_registry.seeds import SCENE_ATOM_AFFINITY, SCENE_CONFLICT_PRECHECK
from app.core.rbac import OPERATIONS, require_any_role
from app.core.skill7.schemas import CandidateInput, DeliverRunRequest
from app.core.skill7.service import deliver_generated_run
from app.product.atom import atom_rules
from app.product.atom.models import EMBEDDING_DIM, ProductAtomInstance
from app.product.fieldpool.models import FieldPool, FPDimension
from app.product.product_intake.models import ProductSpace

SYSTEM_ACTOR = Actor(id="system:llm-gateway", roles=[])


class AtomExpandInvokeNotFound(Exception):
    pass


class AtomExpandInvokeState(Exception):
    pass


class AtomExpandOutputInvalid(Exception):
    pass


async def invoke_atom_expand(
    session: AsyncSession,
    product_space_id: str,
    body: AtomExpandInvokeRequest,
    trigger_actor: Actor,
):
    require_any_role(trigger_actor, OPERATIONS)

    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise AtomExpandInvokeNotFound(product_space_id)

    pool = (
        await session.scalars(
            select(FieldPool).where(FieldPool.product_space_id == product_space_id)
        )
    ).first()
    if pool is None:
        # 与 submit_batch 同口径：无池 404，未 approved 409。
        raise AtomExpandInvokeNotFound("field pool not found")
    if pool.gate != "approved":
        raise AtomExpandInvokeState("atoms LLM expand only under an approved FieldPool")

    approved_atoms = list(
        (
            await session.scalars(
                select(ProductAtomInstance)
                .where(
                    ProductAtomInstance.product_space_id == product_space_id,
                    ProductAtomInstance.status.in_(
                        [atom_rules.ATOM_APPROVED, atom_rules.ATOM_FROZEN]
                    ),
                )
                .order_by(ProductAtomInstance.created_at)
            )
        ).all()
    )
    if atom_rules.target_reached(len(approved_atoms), pool.target_atom_max):
        # Q15：达标停拓仅约束 AI 批次（手动追加批次端点不受限）。
        raise AtomExpandInvokeState(
            f"approved atoms {len(approved_atoms)} reached target "
            f"{pool.target_atom_max} (Q15)"
        )

    dims = list(
        (
            await session.scalars(
                select(FPDimension)
                .where(
                    FPDimension.pool_id == pool.pool_id,
                    FPDimension.status == "selected",
                )
                .order_by(FPDimension.sort_order, FPDimension.dimension_id)
            )
        ).all()
    )
    selected = {d.dimension_id: d for d in dims}

    batch_size = body.batch_size or atom_rules.default_batch_size(
        sensitive=bool(ps.sensitive_industry)
    )

    profile = dict(ps.profile_snapshot or {})
    profile_lines = [f"- {key}: {value}" for key, value in profile.items()]

    variables = {
        # 模板渲染用（字符串）：
        "product_profile": "\n".join(profile_lines) or "（无）",
        "sensitive_industry": "是" if ps.sensitive_industry else "否",
        "batch_size": str(batch_size),
        "selected_dimensions": (
            "\n".join(
                f"- {d.dimension_id} | {d.field_name}"
                + (f" | fid={d.fid}" if d.fid else "")
                + (f" | {d.definition}" if d.definition else "")
                for d in dims
            )
            or "（无）"
        ),
        "approved_atoms": (
            "\n".join(
                f"- {atom.dimension_id} | {atom.content}"
                for atom in approved_atoms
            )
            or "（无）"
        ),
        "target_range": f"{pool.target_atom_min}-{pool.target_atom_max}",
        # 合成替身驱动用（机读），不进模板占位：
        "_batch_size": batch_size,
        "_selected_dims": [
            {"dimension_id": d.dimension_id, "field_name": d.field_name} for d in dims
        ],
    }

    invocation = await gateway.invoke(session, SCENE_CONFLICT_PRECHECK, variables)

    try:
        parsed = json.loads(invocation.text)
        raw_size = parsed["batch_size"]
        raw_items = parsed["items"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AtomExpandOutputInvalid(
            f"model output is not a valid CONFLICT-PRECHECK batch JSON: {exc}"
        ) from exc

    if raw_size != batch_size:
        # Q14：批量上限由触发侧给定，模型必须原样回传。
        raise AtomExpandOutputInvalid(
            "model output batch_size must echo the triggered value exactly"
        )
    if not isinstance(raw_items, list) or not raw_items:
        raise AtomExpandOutputInvalid("model output items must be a non-empty list")
    if len(raw_items) > batch_size:
        raise AtomExpandOutputInvalid(
            f"model output has {len(raw_items)} items, exceeding batch size {batch_size} (Q14)"
        )

    items: list[dict] = []
    seen_norm: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise AtomExpandOutputInvalid("each atom item must be an object")
        content = raw.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AtomExpandOutputInvalid("each atom item requires non-empty content")
        content = content.strip()
        norm = atom_rules.normalize_text(content)
        if norm in seen_norm:
            # 结构脏数据在花 embedding token 前拦；submit_batch 会再校一遍。
            raise AtomExpandOutputInvalid(f"duplicate atom content within batch: {content}")
        seen_norm.add(norm)

        dimension_id = raw.get("dimension_id")
        if dimension_id not in selected:
            raise AtomExpandOutputInvalid(
                f"dimension_id {dimension_id!r} is not a selected dimension of the pool"
            )

        ai_risk = raw.get("ai_risk")
        if ai_risk not in atom_rules.RISK_LEVELS:
            raise AtomExpandOutputInvalid(f"unknown ai_risk level: {ai_risk!r}")

        item = {
            "content": content,
            "dimension_id": dimension_id,
            "ai_risk": ai_risk,
        }
        fact_type = raw.get("fact_type")
        if fact_type is not None:
            if fact_type not in atom_rules.PRODUCT_FACT_TYPES:
                raise AtomExpandOutputInvalid(f"unknown fact_type: {fact_type!r}")
            item["fact_type"] = fact_type
        evidence = raw.get("evidence")
        if evidence is not None:
            if not isinstance(evidence, str) or not evidence.strip():
                raise AtomExpandOutputInvalid("evidence must be a non-empty string")
            item["evidence"] = evidence.strip()
        # affinity/cluster_id 及任何模型自报评分一律不带入：以下向量本地计算。
        items.append(item)

    # 第二次调用：批内文本 + 同维已有向量原子（affinity 基），一次 embed。
    basis_atoms: dict[str, list[ProductAtomInstance]] = {}
    basis_texts: list[str] = []
    basis_dim_of: list[str] = []
    for atom in approved_atoms:
        if atom.embedding is not None:
            basis_atoms.setdefault(atom.dimension_id, []).append(atom)
            basis_texts.append(atom.content)
            basis_dim_of.append(atom.dimension_id)

    embedding = await gateway.embed(
        session, SCENE_ATOM_AFFINITY, [item["content"] for item in items] + basis_texts
    )
    if len(embedding.vectors) != len(items) + len(basis_texts):
        raise gateway.GenerationUpstreamError(
            "embedding response row count does not match requested text count"
        )
    item_vectors = embedding.vectors[: len(items)]
    for vector in embedding.vectors:
        if len(vector) != EMBEDDING_DIM:
            raise gateway.GenerationUpstreamError(
                f"embedding dim {len(vector)} != configured {EMBEDDING_DIM}"
            )

    basis_vectors: dict[str, list[list[float]]] = {}
    for dim_id, vector in zip(
        basis_dim_of, embedding.vectors[len(items):], strict=False
    ):
        basis_vectors.setdefault(dim_id, []).append(vector)

    cluster_ids = atom_rules.assign_clusters(
        item_vectors, labels=[item["dimension_id"] for item in items]
    )
    for item, vector, cluster_id in zip(items, item_vectors, cluster_ids, strict=True):
        item["affinity"] = atom_rules.max_affinity(
            vector, basis_vectors.get(item["dimension_id"], [])
        )
        item["cluster_id"] = cluster_id

    embeddings_by_norm = {
        atom_rules.normalize_text(item["content"]): vector
        for item, vector in zip(items, item_vectors, strict=True)
    }

    payload = {"batch_size": batch_size, "items": items}
    candidate_payload = dict(payload)
    # 编排层机读键：投递结构校验/适配器都会剥离，不进 BatchSubmitRequest。
    candidate_payload["_embeddings"] = embeddings_by_norm

    body = DeliverRunRequest(
        skill_id=SCENE_CONFLICT_PRECHECK,
        product_space_id=product_space_id,
        input={
            "profile_key_count": len(profile),
            "sensitive_industry": ps.sensitive_industry,
            "selected_dimension_count": len(dims),
            "approved_atom_count": len(approved_atoms),
            "approved_embedding_count": len(basis_texts),
            "target_atom_min": pool.target_atom_min,
            "target_atom_max": pool.target_atom_max,
            "batch_size": batch_size,
            "chat_scene": SCENE_CONFLICT_PRECHECK,
            "embedding_scene": SCENE_ATOM_AFFINITY,
            "embedding_model_id": embedding.model_id,
        },
        output=payload,
        candidates=[CandidateInput(target_type="atom_batch", payload=candidate_payload)],
        input_tokens=invocation.input_tokens + embedding.input_tokens,
        output_tokens=invocation.output_tokens,
        actor=SYSTEM_ACTOR,
    )
    return await deliver_generated_run(
        session,
        body,
        model_id=invocation.model_id,
        input_cost=invocation.input_cost + embedding.input_cost,
        output_cost=invocation.output_cost,
        currency_code=invocation.currency_code,
    )
