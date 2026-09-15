"""Q91 DAG 规划与加载期校验（纯函数，不做任何 IO）。

YAML 形态（runtime/workflows/*.yaml，既有线性 WF 一字不改即可规划）：
- steps 仍是既有 ``skills`` 列表；没有任何步骤声明 ``needs`` 时退化为顺序链
  （表内相邻即依赖），WF-01..04 全部按此解释。
- 任一 step 声明 ``needs: [skill_id, ...]`` 即显式 DAG；needs 只能引用同一
  WF 内的步骤；同层步骤可被引擎并发执行。
- skill7 人工 Gate 是硬执行边界：只规划第一道 channel=skill7 的 gate 的
  ``after`` 步骤及其全部前驱（候选投递即止，Gate 后不自动触发，Q66）。
"""

from dataclasses import dataclass

from app.core.skill7.registry import all_skills, get_workflow


class DagValidationError(ValueError):
    """WF 声明不合法：未注册引用/未知依赖/环/重复步骤/Gate 锚点缺失。"""


@dataclass(frozen=True)
class OrchestrationPlan:
    wf_id: str
    """拓扑层：同层无依赖关系可并发，层间屏障（按声明序保序）。"""
    levels: tuple[tuple[str, ...], ...]
    """第一道 skill7 gate 的 after 步骤；WF 无 skill7 gate 时为 None。"""
    boundary: str | None

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(node for level in self.levels for node in level)


def _dependency_graph(wf: dict) -> dict[str, list[str]]:
    wf_id = wf.get("wf_id")
    steps = wf.get("skills") or []
    ids = [str(step.get("skill_id")) for step in steps]
    if len(ids) != len(set(ids)):
        raise DagValidationError(f"workflow {wf_id} declares duplicate steps")
    declared = set(ids)
    explicit = any(step.get("needs") for step in steps)
    graph: dict[str, list[str]] = {}
    for index, step in enumerate(steps):
        skill_id = str(step["skill_id"])
        needs = step.get("needs")
        if needs is None and not explicit:
            # 无线性/显式混排：全无 needs 时按声明序退化为顺序链。
            graph[skill_id] = [ids[index - 1]] if index else []
            continue
        deps = [str(dep) for dep in (needs or [])]
        unknown = [dep for dep in deps if dep not in declared]
        if unknown:
            raise DagValidationError(
                f"workflow {wf_id} step {skill_id} needs unknown steps {unknown}"
            )
        graph[skill_id] = deps
    return graph


def _topological_levels(
    ids: list[str], graph: dict[str, list[str]]
) -> list[tuple[str, ...]]:
    """Kahn 分层；同层按 WF 声明序排列，剩余节点无零入度者即环。"""
    remaining = set(ids)
    levels: list[tuple[str, ...]] = []
    while remaining:
        current = tuple(
            skill_id
            for skill_id in ids
            if skill_id in remaining
            and all(dep not in remaining for dep in graph[skill_id])
        )
        if not current:
            raise DagValidationError("workflow declares a dependency cycle")
        levels.append(current)
        remaining.difference_update(current)
    return levels


def _first_skill7_gate(wf: dict, declared: set[str]) -> str | None:
    for gate in wf.get("gates", []):
        after = gate.get("after")
        if after is not None and after not in declared:
            raise DagValidationError(
                f"workflow {wf.get('wf_id')} gate anchors unknown step {after}"
            )
        if gate.get("channel") == "skill7":
            return str(after)
    return None


def plan_workflow(wf_id: str) -> OrchestrationPlan:
    """加载并规划 WF；未注册 WF 抛 RegistryError，声明非法抛 DagValidationError。"""
    wf = get_workflow(wf_id)
    steps = wf.get("skills") or []
    ids = [str(step["skill_id"]) for step in steps]
    declared = set(ids)
    registered = all_skills()
    missing = [skill_id for skill_id in ids if skill_id not in registered]
    if missing:
        raise DagValidationError(
            f"workflow {wf_id} references unregistered skills {missing}"
        )

    boundary = _first_skill7_gate(wf, declared)
    graph = _dependency_graph(wf)
    levels = _topological_levels(ids, graph)

    if boundary is not None:
        # 执行边界 = 第一道 skill7 gate 的 after 步骤 + 其全部前驱；
        # Gate 后的步骤（含 WF-01 第二道 gate 的 TYPE-MATCH）不在本轮规划内。
        executable = {boundary}
        stack = [boundary]
        while stack:
            current = stack.pop()
            for dep in graph[current]:
                if dep not in executable:
                    executable.add(dep)
                    stack.append(dep)
        levels = [
            tuple(skill_id for skill_id in level if skill_id in executable)
            for level in levels
        ]
        levels = [level for level in levels if level]

    return OrchestrationPlan(
        wf_id=wf_id, levels=tuple(levels), boundary=boundary
    )
