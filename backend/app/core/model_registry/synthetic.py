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


BUILDERS: dict[str, Callable[[dict], dict]] = {
    "CAT-RECOG": build_cat_recog,
}
