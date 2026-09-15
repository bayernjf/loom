"""合成驱动的场景级确定性构造器（非 AI，仅本地/测试替身，Q82-5）。

真 LLM 切片上线后这些构造器只在 provider=synthetic 的注册模型上使用；
产出同样必须经 skill7 人工 Gate，不因其确定性而绕行。
"""

from collections.abc import Callable


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
