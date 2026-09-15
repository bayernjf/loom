"""Q91 注册表驱动 DAG 编排原语（14 §2.2 自研编排器的并行/DAG 子集）。

- planner：YAML 声明 → 拓扑分层，加载期校验（未注册引用/未知依赖/环/重复
  步骤/Gate 锚点），纯函数不 IO；skill7 Gate 为执行边界（不跨人工裁决）。
- engine：同层 asyncio 并发 + 层间屏障 + fail-fast；节点处理器调用方注入，
  引擎自身不调模型、不投递候选、不写 skill_runs。
"""

from app.core.orchestration.engine import (
    NodeContext,
    NodeExecutionError,
    NodeHandler,
    run_workflow,
)
from app.core.orchestration.planner import (
    DagValidationError,
    OrchestrationPlan,
    plan_workflow,
)

__all__ = [
    "DagValidationError",
    "NodeContext",
    "NodeExecutionError",
    "NodeHandler",
    "OrchestrationPlan",
    "plan_workflow",
    "run_workflow",
]
