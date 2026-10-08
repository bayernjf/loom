"""17 池池名（迁移 0052 与测试的单一事实源）。

池名不在这儿重列——它已经有一个权威定义：`pa_rules.WEIGHT_KEYS_17`（Q40 统一校验器
"键必须落在 17 池内"用的就是它）。在这里重抄一份只会让两处各自漂移，故直接引用。
**选项列表本身原文未给出**（docs/02 Q43 只定"池→选项列表做配置字典"），所以种子只建池、
`options` 留空数组由运营经管理面回填——禁臆造业务事实。
"""

from app.platform.platform_adaptation.pa_rules import WEIGHT_KEYS_17

POOL_KEYS: tuple[str, ...] = WEIGHT_KEYS_17
