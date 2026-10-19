#!/usr/bin/env python3
"""Q372：覆盖率 diff 回归门——「新增代码不得裸奔」。

Q229 口径：docs/16 §4 的全局覆盖率阈值是【建议】、刻意不接 --cov-fail-under
（升门属裁决）；本脚本是另一件事——**本次变更新增的行若大面积未被测试覆盖**，
说明新逻辑没测试保护就合入，属可工程自决的回归风险，故做成可执行门。

机制：
1. 读 pytest --cov=app 产出的 coverage.json（CI 里在 Pytest 步骤生成）。
2. git diff（--unified=0）取本次变更中新增的行（相对 --base 引用，PR 场景传
   origin/dev；本地未推送可用 HEAD^ 或任意 base）。
3. 只统计 `app/**/*.py` 的新增行；某行在 coverage.json 该文件的 lines 映射中
   计数 > 0 即视为被覆盖。
4. 每文件新增行覆盖率 < 阈值（默认 80%，工程默认值、可用 --threshold 调）判红；
   被改文件完全没有 coverage 数据（未 import 进测试）同样判红。

排除：`app/core/config.py` 与 `**/seeds.py`（配置载体/种子，历来不测）；
`app/**/schemas.py`（pydantic 声明，几乎全命中 EXCLUDE/类型行）——这些文件只
报告不判红。

用法：
    python scripts/check_coverage_diff.py coverage.json [--base origin/dev]
        [--threshold 80] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

APP_RE = re.compile(r"^app/.*\.py$")
REPORT_ONLY_RE = re.compile(r"^app/.*(?:/config\.py|/schemas\.py|.*seeds\.py)$")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")


def git_diff_new_lines(base: str) -> dict[str, list[int]]:
    """返回 {相对仓库根的文件路径: [新增行号...]}。"""
    cmd = ["git", "diff", "--unified=0", base, "--", "backend/app"]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        # base 不存在（如首次 PR 无 origin/dev）时退回 HEAD^。
        proc = subprocess.run(
            ["git", "diff", "--unified=0", "HEAD^", "--", "backend/app"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    out: dict[str, list[int]] = {}
    current: str | None = None
    new_line = 0
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            m = FILE_RE.match(line)
            fname = m.group(1) if m else None
            # 从仓库根 diff 时路径带 backend/ 前缀，剥掉与 coverage 报告对齐。
            if fname and fname.startswith("backend/"):
                fname = fname[len("backend/"):]
            current = fname
            continue
        if current is None:
            continue
        if line.startswith("@@"):
            hm = HUNK_RE.match(line)
            if hm:
                new_line = int(hm.group(1))
            continue
        if line.startswith("+"):
            if not line.startswith("+++"):
                out.setdefault(current, []).append(new_line)
            new_line += 1
        elif line.startswith("-"):
            continue  # 删除行不占新行号
        else:
            new_line += 1  # unified=0 时不应有上下文行；防御性推进
    return out


def load_covered(data: dict) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for fname, info in data.get("files", {}).items():
        if not APP_RE.match(fname):
            continue
        # coverage.py json 报告：executed_lines 是被执行行号列表（count>0 语义）。
        out[fname] = {int(ln) for ln in info.get("executed_lines", [])}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage", help="pytest --cov-report=json 产物路径")
    parser.add_argument("--base", default="origin/dev", help="diff 基准引用")
    parser.add_argument("--threshold", type=float, default=80.0,
                        help="新增行覆盖率阈值（工程默认 80%，可调）")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    cov_path = Path(args.coverage)
    if not cov_path.exists():
        print(f"::error::coverage file {cov_path} missing", file=sys.stderr)
        return 1
    data = json.loads(cov_path.read_text(encoding="utf-8"))
    covered = load_covered(data)
    new_lines = git_diff_new_lines(args.base)

    report: list[dict] = []
    failures: list[str] = []
    for fname in sorted(new_lines):
        if not APP_RE.match(fname):
            continue
        lines = new_lines[fname]
        hits = set(lines) & covered.get(fname, set())
        pct = round(100.0 * len(hits) / len(lines), 1) if lines else 100.0
        report_only = bool(REPORT_ONLY_RE.match(fname))
        ok = pct >= args.threshold
        if not ok and not report_only:
            failures.append(
                f"{fname}: 新增 {len(lines)} 行，覆盖 {len(hits)} 行（{pct}% < {args.threshold}%{'' if report_only else ' [FAIL]'}"
            )
        report.append({
            "file": fname,
            "new_lines": len(lines),
            "covered_new": len(hits),
            "percent": pct,
            "report_only": report_only,
        })

    if args.json:
        print(json.dumps({"failures": failures, "files": report}, ensure_ascii=False, indent=2))
    else:
        for r in sorted(report, key=lambda x: x["percent"]):
            tag = "  (仅报告)" if r["report_only"] else ""
            status = "[OK]" if r["percent"] >= args.threshold or r["report_only"] else "[FAIL]"
            print(
                f"  {status} {r['file']}: 新增 {r['new_lines']} 行 覆盖 {r['covered_new']} "
                f"({r['percent']}%){tag}"
            )
        if failures:
            print(f"\n[FAIL] {len(failures)} 个文件新增行覆盖率低于 {args.threshold}%（Q372 diff 门）", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
        else:
            print(f"[OK] 全部新增行覆盖率 ≥ {args.threshold}%（Q372 diff 门）")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
