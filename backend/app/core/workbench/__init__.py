"""统一审核工作台（Q70 一期，Q93/C1.37）。

跨 target_type 的 skill7 候选统一队列 + 置信度批量通过；派单/10% 抽检/
6 场景细分属 Q70 二期，不做。SLA 待办自动挂接（Q70②）亦不在本切片。
"""

from app.core.workbench import service

__all__ = ["service"]
