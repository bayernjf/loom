"""Q262 layerSpaces 通用底座种子单一事实源（迁移 0047 与测试共用）。

docs/04 §2.16（line 1261）：四层维度名原文完整；原子值【原文未给出，待补】
不种子（publish_slots 先例）。
"""

# code -> (层名, 维度名元组)
LAYER_DIMENSIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "strategy": ("策略层", ("认知阶段", "目的", "强度", "角度", "情绪", "CTA")),
    "structure": ("结构层", ("标题", "钩子", "开头", "中段", "结尾", "脚本")),
    "expression": ("表达层", ("语气", "本地化", "直白度", "软化映射", "视觉", "符号")),
    "compliance": ("合规层", ("CP-BAN 禁用", "CP-DOWN 降级", "CP-LAW 法审触发", "CP-CLEAN 清洗替换")),
}
