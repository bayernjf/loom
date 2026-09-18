"""合成驱动的场景级确定性构造器（非 AI，仅本地/测试替身，Q82-5）。

真 LLM 切片上线后这些构造器只在 provider=synthetic 的注册模型上使用；
产出同样必须经 skill7 人工 Gate，不因其确定性而绕行。
"""

import hashlib
import math
import re
from collections import Counter
from collections.abc import Callable
from itertools import pairwise

from app.product.atom.models import EMBEDDING_DIM


def _signal_score(text: str) -> float:
    # 长度分档的确定性伪评分：短文本中置信、长文本高置信（便于集成测试造分支）。
    score = 0.75
    if len(text) >= 10:
        score += 0.20
    if len(text) >= 20:
        score += 0.04
    return min(score, 0.99)


def build_cat_recog(variables: dict) -> dict:
    profile = variables.get("_profile", {}) or {}
    signals = {
        key: round(_signal_score(str(profile.get(key, ""))), 4)
        for key in variables.get("_signal_keys", [])
    }
    options = variables.get("_category_options", []) or []
    confidences = [0.95, 0.80]
    candidates = [
        {"category_id": opt["category_id"], "conf": confidences[index]}
        for index, opt in enumerate(options[:2])
    ]
    return {"signals": signals, "candidates": candidates}


def build_pwc_builder(variables: dict) -> dict:
    """PWC-BUILDER 结构替身（Q83-3）：只按维度确定性配对，不造任何评分/目的。

    取维度序下首维的第一个 approved 原子，与其余各维第一个原子逐一配对；
    logic/fit/weight/goals 一律不出（goals 空数组），评分在 M5 漏斗按 Q22b
    子分缺失转人工 Gate。
    """
    atoms = variables.get("_approved_atoms", []) or []
    by_dim: dict[str, list[str]] = {}
    for atom in atoms:
        dim = atom.get("dimension_id")
        if dim:
            by_dim.setdefault(dim, []).append(atom["atom_id"])
    dims = sorted(by_dim)
    combos = []
    if len(dims) >= 2:
        anchor = by_dim[dims[0]][0]
        for dim in dims[1:6]:  # 结构夹具：至多 5 条
            combos.append({"atom_ids": [anchor, by_dim[dim][0]], "goals": []})
    return {"combos": combos}


def build_type_match(variables: dict) -> dict:
    """TYPE-MATCH 结构替身（Q84-3）：只按 G2 覆盖率缺口造结构提案，不打任何分。

    原样回传 category_id/required_fids；为每个未被 active G2 fid 覆盖的必填位
    产一条 field_name 提案（definition 为确定性结构说明）；覆盖已足时给空数组。
    """
    required = list(variables.get("_required_fids", []) or [])
    active = set(variables.get("_active_fids", []) or [])
    missing = [fid for fid in required if fid not in active]
    return {
        "category_id": variables.get("_category_id"),
        "required_fids": required,
        "l4_proposals": [
            {
                "field_name": f"待补字段·{fid}",
                "definition": "synthetic TYPE-MATCH 覆盖率缺口结构提案",
            }
            for fid in missing
        ],
    }


def build_dim_merge(variables: dict) -> dict:
    """DIM-MERGE 结构替身（Q85）：从有界输入确定性拼合规整方案。

    active G2 字段逐条复用为 product_attribute 维度（source_ref=g2:<fid>），
    不足 dim_min 时按 profile_snapshot 键/占位名补新字段维度（无 fid）；
    敏感行业补一条 risk_control（source_ref=industry_tag:<标签>）。
    confidence 固定 0.9（结构占位，不模拟真实置信分布，Q85-3）。
    """
    routes = list(variables.get("_routes", []) or [])
    first_route = routes[0]["route"] if routes else "user_input"
    risk_route = next(
        (r["route"] for r in routes if "risk" in r["route"]), first_route
    )
    dim_min = int(variables.get("_dim_min", 3))
    dim_max = int(variables.get("_dim_max", 8))
    sensitive = bool(variables.get("_sensitive"))

    capacity = dim_max - (1 if sensitive else 0)
    dimensions = [
        {
            "field_name": f["field_name"],
            "role": "product_attribute",
            "source_route": first_route,
            "confidence": 0.9,
            "source_ref": f"g2:{f['fid']}",
            "fid": f["fid"],
        }
        for f in (variables.get("_active_fields", []) or [])[:capacity]
    ]

    profile = dict(variables.get("_profile", {}) or {})
    for key in list(profile.keys()):
        if len(dimensions) >= min(dim_min, capacity):
            break
        dimensions.append({
            "field_name": str(key),
            "role": "product_attribute",
            "source_route": first_route,
            "confidence": 0.9,
            "source_ref": f"product_profile:{key}",
            "definition": "synthetic DIM-MERGE 资料键结构提案",
        })
    n = 1
    active_fids = [f["fid"] for f in (variables.get("_active_fields", []) or [])]
    fallback_ref = (
        f"product_profile:{next(iter(profile))}"
        if profile
        else (f"g2:{active_fids[0]}" if active_fids else None)
    )
    while len(dimensions) < min(dim_min, capacity) and capacity >= 1 and fallback_ref:
        dimensions.append({
            "field_name": f"待补维度·{n}",
            "role": "product_attribute",
            "source_route": first_route,
            "confidence": 0.9,
            "source_ref": fallback_ref,
            "definition": "synthetic DIM-MERGE 占位结构提案",
        })
        n += 1

    if sensitive and len(dimensions) < dim_max:
        tag = variables.get("_industry_tag") or "sensitive"
        dimensions.append({
            "field_name": "合规风险控制",
            "role": "risk_control",
            "source_route": risk_route,
            "confidence": 0.9,
            "source_ref": f"industry_tag:{tag}",
            "definition": "synthetic DIM-MERGE 敏感行业风控结构提案",
        })

    return {
        "target_atom_min": variables.get("_target_atom_min"),
        "target_atom_max": variables.get("_target_atom_max"),
        "dimensions": dimensions,
    }


BUILDERS: dict[str, Callable[[dict], dict]] = {
    "CAT-RECOG": build_cat_recog,
    "PWC-BUILDER": build_pwc_builder,
    "TYPE-MATCH": build_type_match,
    "DIM-MERGE": build_dim_merge,
}


# ---------- embedding 替身（Q86 ATOM-AFFINITY） -----------------------------------

# 每个选中维度产出的两条候选共享的长前缀：仅末字不同（甲/乙），使确定性
# 字袋向量的余弦 ≥ 成簇线（0.9），用于在无真实模型时复现 Q19 成簇路径。
_CP_SHARED = (
    "synthetic conflict precheck "
    "这是用于字段原子池扩充的合成冲突预检确定性结构候选条目内容"
)


def build_conflict_precheck(variables: dict) -> dict:
    """CONFLICT-PRECHECK 结构替身（Q86）：每个选中维度产一对近似原子。

    两条内容共享长前缀、仅末字不同（归一化后不重复，余弦 ≥ 0.9 成簇）；
    不出 affinity/cluster_id（由编排侧本地计算），ai_risk 固定 low（词表
    强制升级仍由 submit_batch 执行），不造 fact_type/evidence。
    """
    batch_size = int(variables.get("_batch_size", 1))
    dims = list(variables.get("_selected_dims", []) or [])
    items: list[dict] = []
    for dim in dims:
        if len(items) >= batch_size:
            break
        base = _CP_SHARED + str(dim.get("field_name") or dim["dimension_id"])
        items.append({
            "content": base + "甲",
            "dimension_id": dim["dimension_id"],
            "ai_risk": "low",
        })
        if len(items) < batch_size:
            items.append({
                "content": base + "乙",
                "dimension_id": dim["dimension_id"],
                "ai_risk": "low",
            })
    return {"batch_size": batch_size, "items": items}


BUILDERS["CONFLICT-PRECHECK"] = build_conflict_precheck


def build_article_gen(variables: dict) -> dict:
    """ARTICLE-GEN 结构替身（P4/Q119）：从 FCW 原料确定性拼一篇占位正文。"""
    final_id = str(variables.get("_final_id", ""))
    goal = str(variables.get("_goal", ""))
    language = str(variables.get("language") or "zh-CN")
    if language != "zh-CN":
        return {
            "body": (
                f"synthetic article title ({goal or 'unspecified'})\n"
                f"synthetic ARTICLE-GEN placeholder body "
                f"(final_id={final_id}, goal={goal}, language={language})"
            ),
        }
    return {
        "body": (
            f"synthetic 内容标题（{goal or '未指定目的'}）\n"
            f"synthetic ARTICLE-GEN 占位正文（final_id={final_id}，goal={goal}）"
        ),
    }


BUILDERS["ARTICLE-GEN"] = build_article_gen


def build_article_qc(variables: dict) -> dict:
    """ARTICLE-QC 结构替身（P4/Q120）：对正文确定性打分，只评不改写。

    供集成测试造高/低分支：正文含哨兵 "[LOW_QC]" 时给低于阈值的 0.62；
    空正文给 0.55；其余确定性给 0.92（≥ content.ai_quality_threshold 默认 0.85）。
    该分仅为辅助参考（Q57），不驱动自动发证或驳回。
    """
    body = str(variables.get("body") or "")
    if "[LOW_QC]" in body:
        return {"score": 0.62, "issues": [{"code": "low_quality", "message": "synthetic low-quality marker"}]}
    if not body.strip():
        return {"score": 0.55, "issues": [{"code": "empty_body", "message": "body is empty"}]}
    return {"score": 0.92, "issues": []}


BUILDERS["ARTICLE-QC"] = build_article_qc


def _embed_one(text: str) -> list[float]:
    # 字袋哈希向量：ascii 词 + CJK 单字 + CJK 相邻二元组，各桶 ±1 计数后
    # L2 归一化。相同文本必相同向量；共享长前缀的文本余弦高（确定性、无随机）。
    lowered = text.lower()
    ascii_words = re.findall(r"[a-z0-9]+", lowered)
    cjk = re.findall(r"[一-鿿]", lowered)
    tokens = ascii_words + cjk + [a + b for a, b in pairwise(cjk)]
    counts = Counter(tokens)
    vec = [0.0] * EMBEDDING_DIM
    for token, count in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % EMBEDDING_DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[bucket] += sign * count
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else [0.0] * EMBEDDING_DIM


def embed_texts(texts: list[str]) -> list[list[float]]:
    return [_embed_one(t) for t in texts]


EMBED_BUILDERS: dict[str, Callable[[list[str]], list[list[float]]]] = {
    "ATOM-AFFINITY": embed_texts,
}
