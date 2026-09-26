"""Contract guard for the GitHub Actions CI workflow (Q111).

The workflow is the staging gate collection from docs/17 and docs/08: every
locally agreed gate must be wired in, so a workflow edit cannot silently drop
a gate. This test parses the YAML statically; it does not execute Actions.
"""

from pathlib import Path

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
