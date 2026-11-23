"""内容目的字典（Q25）的配比种子常量（Q44）。

PRD line 1090 只给出五类目的的单边界，原文未给的另一边保持 NULL、不臆造。
这里集中放播种值，迁移 0067 与测试都引用本模块，禁止二次抄写。

文件名为 ``seeds.py``，按 Q9 哨兵测试的既定排除规则，数值载体不参与
``test_no_magic_numbers`` 的棘轮扫描；业务代码不得从本模块取运行时阈值。
"""

from __future__ import annotations

from app.product.condition.pwc_rules import (
    GOAL_CONVERSION,
    GOAL_EDUCATION,
    GOAL_ENGAGEMENT,
    GOAL_RETENTION,
    GOAL_TRUST,
)

CONTENT_GOAL_RATIO_DEFAULTS: dict[str, tuple[float | None, float | None]] = {
    GOAL_ENGAGEMENT: (None, 0.40),
    GOAL_CONVERSION: (None, 0.30),
    GOAL_EDUCATION: (0.15, None),
    GOAL_TRUST: (0.15, None),
    GOAL_RETENTION: (0.10, None),
}
