"""M10-Q Evaluation runner gate semantics (Q77).

eval/ 在 backend 包之外（15 目录规划），按文件路径加载 runner；
runner 自身 import targets 依赖 eval/ 在 sys.path。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO_ROOT / "eval"


@pytest.fixture(scope="module")
def eval_runner():
    if str(EVAL_DIR) not in sys.path:
        sys.path.insert(0, str(EVAL_DIR))
    spec = importlib.util.spec_from_file_location("loom_eval_runner", EVAL_DIR / "runner.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_suites_pass(eval_runner):
    assert eval_runner.main(["--root", str(EVAL_DIR)]) == 0


def test_failing_case_returns_nonzero(eval_runner, tmp_path):
    root = tmp_path / "eval"
    suite = root / "datasets" / "skills"
    suite.mkdir(parents=True)
    (suite / "X.yaml").write_text(
        """
skill_id: X
cases:
  - id: good
    target: overlap_ratio
    input: {a: [a1, a2], b: [a2, a3]}
    expected: 0.3333333333333333
    tolerance: 0.000000001
  - id: bad
    target: overlap_ratio
    input: {a: [a1], b: [a1]}
    expected: 0.5
  - id: unknown-target
    target: does_not_exist
    input: {}
    expected: null
""",
        encoding="utf-8",
    )
    assert eval_runner.main(["--root", str(root)]) == 1


def test_missing_suites_returns_nonzero(eval_runner, tmp_path):
    assert eval_runner.main(["--root", str(tmp_path / "empty")]) == 1
