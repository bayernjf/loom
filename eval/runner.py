"""Evaluation Dataset / Golden Cases regression runner (M10-Q, Q77).

用法（仓库根目录，backend venv）：
    backend/.venv/bin/python eval/runner.py

扫描 eval/datasets/skills/ 与 eval/golden_cases/skills/ 下的 YAML 案例集，
逐 case 调用 targets.py 注册的确定性 Skill 替身函数，与 expected 比对；
任一失败/错误则退出码 1（staging Evaluation 回归闸门，17 §CI/CD）。
"""

import argparse
import math
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
DATASETS_DIR = Path("datasets/skills")
GOLDEN_DIR = Path("golden_cases/skills")


def _add_backend_to_path() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def _compare(actual, expected, tolerance: float, path: str = "") -> list[str]:
    diffs: list[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path or '$'}: expected dict, got {type(actual).__name__}"]
        for key, exp in expected.items():
            if key not in actual:
                diffs.append(f"{path}.{key}: missing in actual")
            else:
                diffs.extend(
                    _compare(actual[key], exp, tolerance, f"{path}.{key}")
                )
        return diffs
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path or '$'}: expected list, got {type(actual).__name__}"]
        if len(actual) != len(expected):
            diffs.append(
                f"{path}: list length differs (expected {len(expected)}, got {len(actual)})"
            )
        for i, (a, e) in enumerate(zip(actual, expected)):
            diffs.extend(_compare(a, e, tolerance, f"{path}[{i}]"))
        return diffs
    if isinstance(expected, float) or isinstance(actual, float):
        if expected is None or actual is None or not isinstance(
            expected, int | float
        ) or not isinstance(actual, int | float):
            if actual != expected:
                diffs.append(f"{path}: expected {expected!r}, got {actual!r}")
            return diffs
        if math.isnan(float(expected)) or math.isnan(float(actual)):
            if not (math.isnan(float(expected)) and math.isnan(float(actual))):
                diffs.append(f"{path}: expected {expected!r}, got {actual!r}")
            return diffs
        if abs(float(actual) - float(expected)) > tolerance:
            diffs.append(
                f"{path}: expected {expected!r} ±{tolerance}, got {actual!r}"
            )
        return diffs
    if actual != expected:
        diffs.append(f"{path}: expected {expected!r}, got {actual!r}")
    return diffs


def load_suite(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not data or not isinstance(data.get("cases"), list):
        raise ValueError(f"{path}: missing 'cases' list")
    return data["cases"]


def run_dir(root: Path, rel_dir: Path, targets: dict) -> tuple[int, int, list[str]]:
    suite_dir = root / rel_dir
    if not suite_dir.exists():
        return 0, 0, []
    total = 0
    failed = 0
    lines: list[str] = []
    for path in sorted(suite_dir.glob("*.yaml")):
        cases = load_suite(path)
        file_fails = 0
        for case in cases:
            total += 1
            name = f"{path.name}::{case.get('id', total)}"
            target_name = case.get("target")
            if target_name not in targets:
                file_fails += 1
                lines.append(f"  FAIL {name}: unknown target {target_name!r}")
                continue
            tolerance = float(case.get("tolerance", 1e-9))
            try:
                actual = targets[target_name](case.get("input", {}))
                diffs = _compare(actual, case["expected"], tolerance)
            except Exception as exc:  # noqa: BLE001 — runner reports every target error
                file_fails += 1
                lines.append(f"  FAIL {name}: target raised {type(exc).__name__}: {exc}")
                continue
            if diffs:
                file_fails += 1
                lines.append(f"  FAIL {name}:")
                lines.extend(f"    {d}" for d in diffs)
        failed += file_fails
        status = "PASS" if file_fails == 0 else f"FAIL ({file_fails}/{len(cases)})"
        lines.append(f"{status}  {rel_dir / path.name}  ({len(cases)} cases)")
    return total, failed, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loom Skill evaluation regression")
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT / "eval",
        help="eval directory containing datasets/ and golden_cases/",
    )
    args = parser.parse_args(argv)

    _add_backend_to_path()
    from targets import TARGETS

    grand_total = 0
    grand_failed = 0
    for label, rel in (("Evaluation Dataset", DATASETS_DIR), ("Golden Cases", GOLDEN_DIR)):
        total, failed, lines = run_dir(args.root, rel, TARGETS)
        if total == 0 and not (args.root / rel).exists():
            continue
        print(f"== {label} ==")
        for line in lines:
            print(line)
        print(f"   {total - failed}/{total} passed")
        grand_total += total
        grand_failed += failed

    if grand_total == 0:
        print("no evaluation cases found", file=sys.stderr)
        return 1
    print(f"\n{grand_total - grand_failed}/{grand_total} evaluation cases passed")
    return 1 if grand_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
