#!/usr/bin/env python3
"""Q372：docs 活文档 `file:line` 引用校验（只读）。

背景：docs/02（决策记录）、docs/25（验收台账）、docs/23（审计报告）等活文档大量
以 `path.py:NNN` 引用代码行号作证据锚点；任何正常插行都会让行号漂移（Q309 已
点名"高频污染源"，历批合龙都要连带复查）。本脚本把"漂移"变成可执行检查：

- 引用文件不存在 → 阻断（exit 1）
- 行号越界（引用行 > 文件实际行数）→ 阻断
- 行号指向空行/纯空白 → 阻断（证据行落空，Q309 的三信号之一）
- 其余只统计（含指向注释/长行等，语义判断留给人）

刻意不做：**不接 CI 门**——行号门随任何正常插行变红，设不设门是 Q309 遗留裁决，
本脚本只作本地/提交前人工跑。历史台账（handoff-archive-*）引用不回改，只报告。

用法：
    python scripts/check_docs_line_refs.py [--json] [--include-archives]
默认排除 docs/handoff-archive-*.md（历史台账不判红，Q309 口径）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"

REF_RE = re.compile(r"(?<![\w])((?:backend/)?(?:app|scripts|eval|frontend)/[\w./-]+\.py):(\d+)")


def find_refs(text: str):
    for m in REF_RE.finditer(text):
        yield m.group(1), int(m.group(2))


def resolve(rel: str) -> Path | None:
    # docs 里引用可能带 backend/ 前缀也可能不带（历批两种写法并存）。
    for cand in (rel, f"backend/{rel}"):
        p = REPO_ROOT / cand
        if p.exists():
            return p
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--include-archives", action="store_true",
                        help="连带检查 docs/handoff-archive-*（默认跳过）")
    args = parser.parse_args()

    files = sorted(DOCS_DIR.glob("*.md"))
    if not args.include_archives:
        files = [f for f in files if "handoff-archive" not in f.name]

    problems: list[dict] = []
    total_refs = 0
    checked_files = 0
    for doc in files:
        text = doc.read_text(encoding="utf-8")
        for rel, lineno in find_refs(text):
            total_refs += 1
            target = resolve(rel)
            if target is None:
                problems.append({
                    "doc": doc.name, "ref": f"{rel}:{lineno}",
                    "kind": "missing_file",
                })
                continue
            checked_files += 1
            lines = target.read_text(encoding="utf-8").splitlines()
            if lineno < 1 or lineno > len(lines):
                problems.append({
                    "doc": doc.name, "ref": f"{rel}:{lineno}",
                    "kind": "out_of_range",
                    "file_lines": len(lines),
                })
                continue
            if not lines[lineno - 1].strip():
                problems.append({
                    "doc": doc.name, "ref": f"{rel}:{lineno}",
                    "kind": "blank_line",
                })

    if args.json:
        print(json.dumps({
            "total_refs": total_refs,
            "checked_files": checked_files,
            "problems": problems,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"docs 行号引用: {total_refs} 条（校验 {checked_files} 个文件）")
        if problems:
            print(f"[FAIL] {len(problems)} 处失效引用：")
            for p in problems:
                extra = f"（文件 {p['file_lines']} 行）" if p["kind"] == "out_of_range" else ""
                print(f"  - {p['doc']}  {p['ref']}  [{p['kind']}]{extra}")
        else:
            print("[OK] 无失效引用")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
