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
        "check-products",
        "check-workbench",
        "check-compliance",
        "check-admin",
    ):
        assert f"scripts/{checker}.mjs" in frontend_runs
