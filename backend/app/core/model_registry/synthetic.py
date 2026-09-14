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


BUILDERS: dict[str, Callable[[dict], dict]] = {
    "CAT-RECOG": build_cat_recog,
    "PWC-BUILDER": build_pwc_builder,
}
