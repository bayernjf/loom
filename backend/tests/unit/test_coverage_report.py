"""Coverage reader contract (Q221): it reports, it never fails the build."""

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import coverage_report as cmd


def _file(pct: int, stmts: int) -> dict:
    return {"summary": {"num_statements": stmts, "covered_lines": pct, "percent_covered": 100.0 * pct / stmts}}


def test_splits_core_rule_layer_from_app_total() -> None:
    data = {
        "files": {
            "app/product/atom/atom_rules.py": _file(50, 50),
            "app/product/product_intake/statemachine.py": _file(40, 40),
            "app/content/statemachine.py": _file(15, 30),
            "app/core/effects/service.py": _file(10, 100),
        }
    }
    stats = cmd.summarize(data)
    assert stats["core_files"] == 3 and stats["core_statements"] == 120
    assert stats["core_rules"] == 87.5  # 105 covered / 120
    assert stats["app_statements"] == 220
    assert stats["app_total"] == 52.27  # 115 covered / 220
    assert stats["worst_core"][0]["file"] == "app/content/statemachine.py"


def test_main_prints_both_numbers_and_never_fails(capsys, tmp_path) -> None:
    payload = tmp_path / "coverage.json"
    payload.write_text(
        json.dumps({"files": {"app/product/atom/atom_rules.py": _file(1, 10), "app/core/effects/x.py": _file(0, 10)}}),
        encoding="utf-8",
    )
    assert cmd.main(["coverage_report.py", str(payload)]) == 0
    out = capsys.readouterr().out
    assert "10.0%" in out  # core layer is at the floor here, and CI still exits 0
    assert "【建议】" in out


def test_missing_coverage_file_is_a_warning_not_a_failure(tmp_path, capsys) -> None:
    """没有测量产物时也必须退 0：它是读数，不是门。"""
    rc = cmd.main(["coverage_report.py", str(tmp_path / "absent.json")])
    assert rc == 0
    assert "missing" in capsys.readouterr().err


def test_empty_files_map_does_not_divide_by_zero() -> None:
    stats = cmd.summarize({"files": {}})
    assert stats == {
        "app_total": 0.0,
        "app_statements": 0,
        "core_rules": 0.0,
        "core_statements": 0,
        "core_files": 0,
        "worst_core": [],
    }
