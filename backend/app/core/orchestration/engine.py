"""Q91 DAG 执行器：拓扑分层、同层 asyncio 并发、层间屏障、fail-fast。

引擎只演绎注册表声明，不做业务：节点处理器由调用方按 skill_id 注入
（真实站点接入切片各自走既有 skill7 通道投递/记账，Gate 不跨）。
- 同层并发受进程内信号量约束（LOOM_ORCH_MAX_CONCURRENCY，Q91 接缝③）；
- 同层任一节点失败即取消同层其余任务，整轮失败，不自动重试
  （重试/退避归调用侧，如 Q90 restock 游标，避免双层重试烧 token）；
- 引擎不写 skill_runs；真实节点把 NodeContext.orch_run_id/wf_id 写入
  run.input 做同轮关联（Q91 接缝④，无新表、无迁移）。
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.core.db import settings
from app.core.orchestration.planner import OrchestrationPlan, plan_workflow


class HandlerMissing(LookupError):
    """规划中的节点没有注入处理器。"""


class NodeExecutionError(RuntimeError):
    """同层某节点失败（fail-fast）；completed 为此前已成功的节点（声明序）。"""

    def __init__(
        self,
        *,
        orch_run_id: str,
        node: str,
        reason: str,
        completed: list[str],
    ) -> None:
        super().__init__(
            f"workflow run {orch_run_id} failed at node {node}: {reason}"
        )
        self.orch_run_id = orch_run_id
        self.node = node
        self.reason = reason
        self.completed = completed


@dataclass(frozen=True)
class NodeContext:
    wf_id: str
    orch_run_id: str
    skill_id: str
    """已完成前驱节点的返回值（层间屏障保证依赖全部就绪）。"""
    results: Mapping[str, Any]


NodeHandler = Callable[[NodeContext], Awaitable[Any]]


async def run_workflow(
    wf_id: str,
    handlers: Mapping[str, NodeHandler],
    *,
    max_concurrency: int | None = None,
    orch_run_id: str | None = None,
) -> dict:
    """按 WF 声明跑完一道 skill7 Gate 边界内的全部节点，返回执行报告。"""
    plan: OrchestrationPlan = plan_workflow(wf_id)
    missing = [node for node in plan.nodes if node not in handlers]
    if missing:
        raise HandlerMissing(f"workflow {wf_id} has no handlers for {missing}")

    run_id = orch_run_id or uuid.uuid4().hex
    limit = max_concurrency or settings.orch_max_concurrency
    semaphore = asyncio.Semaphore(limit)
    results: dict[str, Any] = {}
    completed: list[str] = []
    nodes_report: list[dict] = []

    for level_index, level in enumerate(plan.levels):

        async def run_node(skill_id: str) -> tuple[str, Any]:
            async with semaphore:
                value = await handlers[skill_id](
                    NodeContext(
                        wf_id=wf_id,
                        orch_run_id=run_id,
                        skill_id=skill_id,
                        results=results,
                    )
                )
            return skill_id, value

        tasks = {
            skill_id: asyncio.create_task(run_node(skill_id)) for skill_id in level
        }
        gather = asyncio.gather(*tasks.values())
        try:
            gathered = await gather
        except asyncio.CancelledError:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            raise
        except Exception as exc:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            failed_node = next(
                skill_id
                for skill_id in level
                if not tasks[skill_id].cancelled()
                and tasks[skill_id].exception() is exc
            )
            raise NodeExecutionError(
                orch_run_id=run_id,
                node=failed_node,
                reason=type(exc).__name__,
                completed=completed,
            ) from exc

        results.update(gathered)
        completed.extend(level)
        nodes_report.extend(
            {"skill_id": skill_id, "level": level_index, "status": "succeeded"}
            for skill_id in level
        )

    return {
        "orch_run_id": run_id,
        "wf_id": wf_id,
        "boundary": plan.boundary,
        "levels": [list(level) for level in plan.levels],
        "nodes": nodes_report,
        "results": results,
    }
