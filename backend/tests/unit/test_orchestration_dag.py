"""Q91 注册表驱动 DAG 编排原语单测：规划校验 + 同层并发/屏障/fail-fast。

纯单元测试：LOOM_RUNTIME_DIR 指向临时目录构造 WF/Skill 声明，节点处理器为
合成 async 函数（不调模型、不投递候选、不写 skill_runs——引擎本身不做业务）。
"""

import asyncio

import pytest
import yaml

from app.core.orchestration import (
    DagValidationError,
    NodeContext,
    NodeExecutionError,
    plan_workflow,
    run_workflow,
)
from app.core.orchestration.engine import HandlerMissing
from app.core.skill7 import registry


@pytest.fixture
def runtime_dir(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    (root / "skills").mkdir(parents=True)
    (root / "workflows").mkdir()
    monkeypatch.setenv("LOOM_RUNTIME_DIR", str(root))
    registry.reload()
    yield root
    registry.reload()


def add_skill(root, skill_id: str) -> None:
    directory = root / "skills" / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "skill.yaml").write_text(
        yaml.safe_dump({"skill_id": skill_id}), encoding="utf-8"
    )


def add_workflow(root, wf_id: str, steps: list[dict], gates: list[dict] | None = None):
    data: dict = {"wf_id": wf_id, "skills": steps}
    if gates is not None:
        data["gates"] = gates
    (root / "workflows" / f"{wf_id}.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
    )


def step(skill_id: str, needs: list[str] | None = None) -> dict:
    data = {"skill_id": skill_id}
    if needs is not None:
        data["needs"] = needs
    return data


# ---------- planner：声明形态与加载期校验 ----------


def test_no_needs_degrades_to_sequential_chain(runtime_dir):
    for skill_id in ["A", "B", "C"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(runtime_dir, "WF-T", [step("A"), step("B"), step("C")])

    plan = plan_workflow("WF-T")

    assert plan.boundary is None
    assert [list(level) for level in plan.levels] == [["A"], ["B"], ["C"]]
    assert plan.nodes == ("A", "B", "C")


def test_explicit_needs_build_fanout_fanin_levels(runtime_dir):
    for skill_id in ["A", "B", "C", "D"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(
        runtime_dir,
        "WF-T",
        [
            step("A", needs=[]),
            step("B", needs=["A"]),
            step("C", needs=["A"]),
            step("D", needs=["B", "C"]),
        ],
    )

    plan = plan_workflow("WF-T")

    assert [list(level) for level in plan.levels] == [["A"], ["B", "C"], ["D"]]


def test_unknown_need_is_rejected(runtime_dir):
    add_skill(runtime_dir, "A")
    add_workflow(runtime_dir, "WF-T", [step("A", needs=["GHOST"])])

    with pytest.raises(DagValidationError, match="unknown steps"):
        plan_workflow("WF-T")


def test_dependency_cycle_is_rejected(runtime_dir):
    for skill_id in ["A", "B"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(
        runtime_dir,
        "WF-T",
        [step("A", needs=["B"]), step("B", needs=["A"])],
    )

    with pytest.raises(DagValidationError, match="cycle"):
        plan_workflow("WF-T")


def test_duplicate_step_is_rejected(runtime_dir):
    add_skill(runtime_dir, "A")
    add_workflow(runtime_dir, "WF-T", [step("A", needs=[]), step("A", needs=[])])

    with pytest.raises(DagValidationError, match="duplicate"):
        plan_workflow("WF-T")


def test_unregistered_skill_reference_is_rejected(runtime_dir):
    add_workflow(runtime_dir, "WF-T", [step("A")])

    with pytest.raises(DagValidationError, match="unregistered"):
        plan_workflow("WF-T")


def test_gate_anchoring_unknown_step_is_rejected(runtime_dir):
    add_skill(runtime_dir, "A")
    add_workflow(
        runtime_dir,
        "WF-T",
        [step("A")],
        gates=[{"after": "GHOST", "channel": "skill7", "role": "operations"}],
    )

    with pytest.raises(DagValidationError, match="gate anchors unknown"):
        plan_workflow("WF-T")


def test_non_skill7_gate_does_not_bound_the_plan(runtime_dir):
    for skill_id in ["A", "B"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(
        runtime_dir,
        "WF-T",
        [step("A"), step("B")],
        gates=[{"after": "A", "endpoint": "POST /api/human"}],
    )

    plan = plan_workflow("WF-T")

    assert plan.boundary is None
    assert plan.nodes == ("A", "B")


def test_skill7_gate_truncates_plan_to_boundary_and_ancestors(runtime_dir):
    for skill_id in ["A", "B", "C", "D"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(
        runtime_dir,
        "WF-T",
        [step("A"), step("B"), step("C"), step("D")],
        gates=[{"after": "B", "channel": "skill7", "role": "operations"}],
    )

    plan = plan_workflow("WF-T")

    assert plan.boundary == "B"
    assert plan.nodes == ("A", "B")


def test_gate_boundary_in_dag_keeps_all_ancestors_including_parallel_branches(
    runtime_dir,
):
    # A 扇出到 B/C，D fan-in 后挂 Gate；Gate 边界必须包含整条 DAG。
    for skill_id in ["A", "B", "C", "D"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(
        runtime_dir,
        "WF-T",
        [
            step("A", needs=[]),
            step("B", needs=["A"]),
            step("C", needs=["A"]),
            step("D", needs=["B", "C"]),
        ],
        gates=[{"after": "D", "channel": "skill7", "role": "product_reviewer"}],
    )

    plan = plan_workflow("WF-T")

    assert plan.boundary == "D"
    assert [list(level) for level in plan.levels] == [["A"], ["B", "C"], ["D"]]


@pytest.mark.parametrize(
    ("wf_id", "boundary", "levels"),
    [
        ("WF-01", "CAT-RECOG", [["PARSE"], ["UNDERSTAND"], ["CAT-RECOG"]]),
        ("WF-02", "DIM-MERGE", [["FIELDPOOL-PLAN"], ["DIM-SOURCE"], ["DIM-MERGE"]]),
        (
            "WF-03",
            "CONFLICT-PRECHECK",
            [
                ["ATOM-EXPAND"],
                ["ATOM-CANON"],
                ["ATOM-AFFINITY"],
                ["CONFLICT-PRECHECK"],
            ],
        ),
        ("WF-04", "PWC-BUILDER", [["PWC-BUILDER"]]),
    ],
)
def test_shipped_linear_workflows_plan_unchanged(wf_id, boundary, levels):
    # 用仓库自带 runtime/（无 needs → 顺序链），Gate 后步骤不进规划。
    plan = plan_workflow(wf_id)
    assert plan.boundary == boundary
    assert [list(level) for level in plan.levels] == levels


# ---------- engine：并发、屏障、fail-fast、处理器缝 ----------


async def test_run_workflow_executes_levels_and_pipes_upstream_results(runtime_dir):
    for skill_id in ["A", "B", "C", "D"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(
        runtime_dir,
        "WF-T",
        [
            step("A", needs=[]),
            step("B", needs=["A"]),
            step("C", needs=["A"]),
            step("D", needs=["B", "C"]),
        ],
    )
    seen: list[str] = []

    async def handler(ctx: NodeContext):
        seen.append(ctx.skill_id)
        if ctx.skill_id == "D":
            assert ctx.results["B"] == "b" and ctx.results["C"] == "c"
        return ctx.skill_id.lower()

    report = await run_workflow(
        "WF-T",
        {skill_id: handler for skill_id in ["A", "B", "C", "D"]},
        orch_run_id="run-1",
    )

    assert seen[:1] == ["A"]
    assert set(seen[1:3]) == {"B", "C"}
    assert seen[3] == "D"
    assert report["orch_run_id"] == "run-1"
    assert report["wf_id"] == "WF-T"
    assert report["boundary"] is None
    assert report["results"] == {"A": "a", "B": "b", "C": "c", "D": "d"}
    assert [node["status"] for node in report["nodes"]] == ["succeeded"] * 4


async def test_same_level_nodes_run_under_concurrency_cap(runtime_dir):
    for skill_id in ["A", "B", "C", "D"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(
        runtime_dir,
        "WF-T",
        [step(skill_id, needs=[]) for skill_id in ["A", "B", "C", "D"]],
    )
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def handler(ctx: NodeContext) -> str:
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        async with lock:
            active -= 1
        return ctx.skill_id

    await run_workflow(
        "WF-T",
        {skill_id: handler for skill_id in ["A", "B", "C", "D"]},
        max_concurrency=2,
    )

    assert max_active == 2


async def test_layer_barrier_holds_next_level_until_whole_level_finishes(runtime_dir):
    for skill_id in ["A", "B", "C"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(
        runtime_dir,
        "WF-T",
        [
            step("A", needs=[]),
            step("B", needs=[]),
            step("C", needs=["A", "B"]),
        ],
    )
    log: list[str] = []

    async def slow(ctx: NodeContext) -> str:
        log.append(f"{ctx.skill_id}:start")
        await asyncio.sleep(0.02)
        log.append(f"{ctx.skill_id}:end")
        return ctx.skill_id

    await run_workflow("WF-T", {"A": slow, "B": slow, "C": slow})

    assert log.index("C:start") > max(log.index("A:end"), log.index("B:end"))


async def test_fail_fast_cancels_siblings_and_skips_later_levels(runtime_dir):
    for skill_id in ["A", "B", "C", "D"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(
        runtime_dir,
        "WF-T",
        [
            step("A", needs=[]),
            step("B", needs=["A"]),
            step("C", needs=["A"]),
            step("D", needs=["B", "C"]),
        ],
    )
    ran_d = False
    c_cancelled = False

    async def ok(ctx: NodeContext) -> str:
        return ctx.skill_id

    async def boom(ctx: NodeContext) -> str:
        raise RuntimeError("upstream 502")

    async def blocked(ctx: NodeContext) -> str:
        nonlocal c_cancelled
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            c_cancelled = True
            raise
        return ctx.skill_id

    async def never(ctx: NodeContext) -> str:
        nonlocal ran_d
        ran_d = True
        return ctx.skill_id

    with pytest.raises(NodeExecutionError) as exc_info:
        await run_workflow("WF-T", {"A": ok, "B": boom, "C": blocked, "D": never})

    error = exc_info.value
    assert error.node == "B"
    assert error.reason == "RuntimeError"
    assert error.completed == ["A"]
    assert c_cancelled is True
    assert ran_d is False


async def test_missing_handler_is_rejected_before_execution(runtime_dir):
    for skill_id in ["A", "B"]:
        add_skill(runtime_dir, skill_id)
    add_workflow(runtime_dir, "WF-T", [step("A"), step("B")])

    async def ok(ctx: NodeContext) -> str:
        return ctx.skill_id

    with pytest.raises(HandlerMissing, match="B"):
        await run_workflow("WF-T", {"A": ok})


async def test_orch_run_id_is_propagated_or_generated(runtime_dir):
    add_skill(runtime_dir, "A")
    add_workflow(runtime_dir, "WF-T", [step("A")])
    seen: list[NodeContext] = []

    async def capture(ctx: NodeContext) -> str:
        seen.append(ctx)
        return "ok"

    report = await run_workflow("WF-T", {"A": capture}, orch_run_id="run-xyz")
    assert seen[0].orch_run_id == "run-xyz"
    assert seen[0].wf_id == "WF-T"
    assert report["orch_run_id"] == "run-xyz"

    auto = await run_workflow("WF-T", {"A": capture})
    assert len(auto["orch_run_id"]) == 32
