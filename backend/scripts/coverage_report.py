"""Coverage reader for CI - **measurement only, never a gate**.

docs/16 §4 sets a coverage *target* marked 【建议】; promoting it to a hard gate is
a ruling the owner has not made, so this script only reports and always exits 0.

"Core rule layer" is docs/16 §4's 评分/权重/Guard/状态机, operationalized here once as
``app/**/*_rules.py`` + ``app/**/statemachine.py`` so the two documents that cite the
90% target cannot each mean something different by it.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_CORE = re.compile(r"app/[\w/]*_rules\.py$|app/[\w/]*statemachine\.py$")


def _rows(data: dict) -> list[tuple[str, float, int, int]]:
    out = []
    for fname, info in data.get("files", {}).items():
        s = info.get("summary", {})
        stmts = int(s.get("num_statements", 0))
        covered = int(s.get("covered_lines", 0))
        pct = float(s.get("percent_covered", 0.0))
        out.append((fname, pct, stmts, covered))
    return out


def summarize(data: dict) -> dict:
    rows = _rows(data)
    total_stmts = sum(r[2] for r in rows)
    total_cov = sum(r[3] for r in rows)
    core = [r for r in rows if _CORE.search(r[0])]
    core_stmts = sum(r[2] for r in core)
    core_cov = sum(r[3] for r in core)

    def pct(part: int, whole: int) -> float:
        return round(100.0 * part / whole, 2) if whole else 0.0

    return {
        "app_total": pct(total_cov, total_stmts),
        "app_statements": total_stmts,
        "core_rules": pct(core_cov, core_stmts),
        "core_statements": core_stmts,
        "core_files": len(core),
        "worst_core": [
            {"file": f, "percent": round(p, 2), "statements": n}
            for f, p, n, _ in sorted(core, key=lambda r: r[1])[:5]
        ],
    }


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    if not path.exists():
        print(f"::warning::coverage file {path} missing - nothing measured", file=sys.stderr)
        return 0
    stats = summarize(json.loads(path.read_text(encoding="utf-8")))
    lines = [
        "## Coverage（仅测量，不设门）",
        "",
        f"- 全系统 `app/`：**{stats['app_total']}%**（{stats['app_statements']} 条语句）",
        (
            f"- 核心规则层（`app/**/*_rules.py` ＋ `app/**/statemachine.py`，共 {stats['core_files']} 个文件）："
            f"**{stats['core_rules']}%**（{stats['core_statements']} 条语句）"
        ),
    ]
    for row in stats["worst_core"]:
        lines.append(f"  - {row['file']}：{row['percent']}%（{row['statements']} 条）")
    lines += [
        "",
        (
            "docs/16 §4 的两个阈值（核心 ≥90%／全系统 ≥70%）仍是【建议】——**本步不因低阈值而失败**，"
            "把它变成门需要负责人裁决。"
        ),
    ]
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
