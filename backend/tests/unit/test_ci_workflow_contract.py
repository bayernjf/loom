"""Contract guard for the GitHub Actions CI workflow (Q111).

The workflow is the staging gate collection from docs/17 and docs/08: every
locally agreed gate must be wired in, so a workflow edit cannot silently drop
a gate. This test parses the YAML statically; it does not execute Actions.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _steps(job: dict) -> str:
    return "\n".join(
        (step.get("run", "") if isinstance(step, dict) else "")
        for step in job.get("steps", [])
    )


def test_workflow_wires_every_agreed_gate() -> None:
    data = yaml.safe_load(WORKFLOW.read_text())

    assert "pull_request" in data[True]
    push_branches = data[True]["push"]["branches"]
    assert "main" in push_branches and "dev" in push_branches

    jobs = data["jobs"]
    backend_runs = _steps(jobs["backend"])
    assert "ruff check ." in backend_runs
    assert "python -m pytest" in backend_runs
    assert "python eval/runner.py" in backend_runs

    frontend_runs = _steps(jobs["frontend"])
    assert "npm run typecheck" in frontend_runs
    for checker in (
        "check-tokens",
        "check-nav",
        "check-content",  # Q122：第 8 个 checker（客户内容页）
        "check-products",
        "check-workbench",
        "check-compliance",
        "check-admin",
        "check-settings",  # Q118：第 7 个 checker 接入 CI（Q117 审计发现本地有、CI 漏跑）
    ):
        assert f"scripts/{checker}.mjs" in frontend_runs


def test_every_committed_checker_script_is_wired() -> None:
    # Q118：目录里新增 check-*.mjs 而 CI 漏接时必须红——CI 集合与磁盘集合一致。
    data = yaml.safe_load(WORKFLOW.read_text())
    frontend_runs = _steps(data["jobs"]["frontend"])

    scripts_dir = REPO_ROOT / "frontend" / "scripts"
    on_disk = {p.name for p in scripts_dir.glob("check-*.mjs")}
    in_ci = {
        token.split("/")[-1]
        for token in frontend_runs.split()
        if token.startswith("scripts/check-") and token.endswith(".mjs")
    }
    assert on_disk == in_ci, f"checker drift: disk={on_disk} ci={in_ci}"


def test_migration_gate_is_wired() -> None:
    """Q207：真 PG16 的迁移门必须在 CI；job 被删或某步被摘就判红（Q118 同一手法）。"""
    data = yaml.safe_load(WORKFLOW.read_text())
    jobs = data["jobs"]
    assert "migration" in jobs, (
        "迁移门被摘掉了：ORM⇄迁移漂移与迁移可逆性会重新变成无人值守的事"
    )
    mig = jobs["migration"]
    assert mig["services"]["postgres"]["image"] == "pgvector/pgvector:pg16", (
        "漂移检查必须跑在带 vector 类型的 PG16 上（Q86 的 embedding 列）"
    )
    runs = _steps(mig)
    assert "alembic upgrade head" in runs
    assert "python scripts/dba_schema_check.py" in runs
    assert "alembic downgrade -1" in runs
    # CI 故意不钉死表数：新增表是常态，钉住会让每次合法迁移都假红。
    assert "--expect-tables" not in runs
    # `alembic check` 实测在 HEAD 上报 19 条命名差异（永久红），不得当门用。
    assert "alembic check" not in runs


def test_real_infra_gate_is_wired() -> None:
    """Q209：真容器集成门必须在 CI；job 被删／service 被摘／env 没注入就判红。

    这一族测的是替身（FakeRedis/FakeStreams/sqlite 单连接）证不了的东西：真 PG
    跨连接池的提交可见性与行级锁串行化、真 Redis 的 SET NX/Lua 释放、Streams
    消费组分片与 XCLAIM 接管、pub/sub 跨连接投递。
    """
    data = yaml.safe_load(WORKFLOW.read_text())
    jobs = data["jobs"]
    assert "real-infra" in jobs, (
        "real-infra 门被摘掉了：多副本原语会退回「只在内存替身下自洽」的状态"
    )
    job = jobs["real-infra"]
    services = job.get("services") or {}
    assert services.get("postgres", {}).get("image") == "pgvector/pgvector:pg16", (
        "fence 表的条件 UPDATE 与行级锁必须在真 PG 上验，sqlite 单连接复现不了"
    )
    redis_image = (services.get("redis") or {}).get("image", "")
    assert redis_image.startswith("redis:"), "Streams/lease/pub-sub 需要真 Redis"
    env = job.get("env") or {}
    assert env.get("LOOM_TEST_REAL_PG_DSN"), "缺 PG DSN ⇒ 用例全 skip ⇒ 静默绿灯"
    assert env.get("LOOM_TEST_REAL_REDIS_URL"), "缺 Redis URL ⇒ 用例全 skip ⇒ 静默绿灯"
    runs = _steps(job)
    assert "tests/integration/test_real_infra.py" in runs


def _real_infra_run() -> str:
    data = yaml.safe_load(WORKFLOW.read_text())
    return _steps(data["jobs"]["real-infra"])


def _run_sentinel_block(summary: str, pytest_exit: int = 0) -> int:
    """把 CI 里那段 step 脚本原样取出来跑一遍，用假 `python` 喂一个 summary 末行。

    为什么不只是断言哨兵「文本存在」：env 没设时这一族是「全 skip + exit 0」，
    没有哨兵的 job 会永远绿而从没跑过一行真断言（Q193/Q204 同型教训），而静态
    断言挡不住有人把哨兵改成一句 echo。所以这里喂三种末行真跑它的退出码。
    """
    run = _real_infra_run()
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "python"
        stub.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$FAKE_PYTEST_SUMMARY"\n'
            'exit "${FAKE_PYTEST_EXIT:-0}"\n'
        )
        stub.chmod(0o755)
        env = dict(
            os.environ,
            PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}",
            FAKE_PYTEST_SUMMARY=summary,
            FAKE_PYTEST_EXIT=str(pytest_exit),
        )
        return subprocess.run(
            ["bash", "-c", run], cwd=tmp, env=env, capture_output=True, check=False
        ).returncode


@pytest.mark.parametrize(
    "summary,expected_exit",
    [
        ("9 skipped in 1.35s", 1),  # env 没生效：全 skip，必须红
        ("no tests ran in 0.03s", 1),  # 收集不到：多半路径被改，必须红
        ("9 passed in 6.49s", 0),  # 真跑过：绿
    ],
)
def test_real_infra_skip_sentinel_fires(summary: str, expected_exit: int) -> None:
    assert _run_sentinel_block(summary) == expected_exit, (
        f"哨兵对 summary={summary!r} 的判定不对：expected exit {expected_exit}"
    )
