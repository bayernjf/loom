#!/usr/bin/env python3
"""Q372：前端 lib/api.ts 与后端 openapi 漂移校验（只读，不代处置）。

基准取「代码生成 openapi」（app.openapi()），不依赖运行栈——运行容器镜像可能
滞后于代码（实测旧镜像只有 136 paths，代码生成 219 paths，与 docs/26 §6.1
记载一致）。

判据（两级）：
1. 阻断项（exit 1）：lib/api.ts 引用的请求路径在 openapi 中不存在
   ——前端调 404，属真漂移。路径模板 `${xxx}` 与 openapi `{xxx}` 均视为
   通配段（名字可以不同，如 `${contentId}` vs `{content_id}`）。
2. 提示项（不阻断）：openapi 中 `/api/admin/` 管理口未被 lib/api.ts 引用
   ——合法状态包括「后端先于前端落地」（Q368 平台适配台 AI 入口等刻意不做），
   只打印提示供人工判断。

用法：backend/.venv/bin/python scripts/check_openapi_drift.py
可选：--openapi <path> 直接读已有 openapi.json（跳过代码生成，加速调试）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_TS = REPO_ROOT / "frontend" / "lib" / "api.ts"

# lib/api.ts 的请求路径全部经 request<T>("...") / request("...") 首参给出；
# 支持单/双引号与反引号模板（模板内可出现嵌套 ${...} 表达式）。
REQ_RE = re.compile(r"\brequest(?:\s*<[^>]*>)?\s*\(\s*(['\"`])(.*?)\1", re.DOTALL)
# 平衡花括号的 ${...} 模板（含一层嵌套），如 ${qs ? `?${qs}` : ""}。
TEMPLATE_RE = re.compile(r"\$\{(?:[^{}]|\{[^{}]*\})*\}")
SEG_PARAM_RE = re.compile(r"^\{param\}$")
OPENAPI_PARAM_RE = re.compile(r"^\{.+?\}$")


def norm_seg(seg: str) -> str:
    """把一段路径归一为比较键：openapi {xxx} 与前端 {param} 通配段一律记为 {param}。"""
    if SEG_PARAM_RE.match(seg) or OPENAPI_PARAM_RE.match(seg):
        return "{param}"
    return seg


def norm_path(path: str) -> str:
    return "/".join(norm_seg(s) for s in path.split("/"))


def extract_api_paths(text: str) -> set[str]:
    """提取 lib/api.ts 中全部 request(...) 首参路径模板（去重，已归一化）。"""
    out: set[str] = set()
    for m in REQ_RE.finditer(text):
        raw = TEMPLATE_RE.sub("{param}", m.group(2))
        if raw.startswith("/api/") is False:
            continue
        # 嵌套 ${...}（如 ${qs ? `?${qs}` : ""}）会被 REQ_RE 截断：残留 `${` 或
        # 反引号的候选不可靠，丢弃（该路径若有完整字面量自会单独提取）。
        if "${" in raw or "`" in raw:
            continue
        # 去掉查询串（模板替换后，残余 ? 即查询串）。
        raw = raw.split("?", 1)[0].rstrip("/")
        if not raw:
            continue
        out.add(norm_path(raw))
    return out


def collect_openapi_paths(schema: dict) -> set[str]:
    return {norm_path(p) for p in schema.get("paths", {})}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openapi", help="直接读已有 openapi.json，跳过代码生成")
    args = parser.parse_args()

    if args.openapi:
        with open(args.openapi, "r", encoding="utf-8") as f:
            schema = json.load(f)
    else:
        # 从后端代码生成权威 openapi（不依赖运行容器）。
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.main import app

        schema = app.openapi()

    openapi_paths = collect_openapi_paths(schema)
    api_paths = extract_api_paths(API_TS.read_text(encoding="utf-8"))

    raw_openapi = set(schema.get("paths", {}))
    admin_openapi = {
        norm_path(p)
        for p in raw_openapi
        if p.startswith("/api/admin/")
    }

    missing = sorted(api_paths - openapi_paths)  # 悬空引用：前端调 404
    unlinked = sorted(admin_openapi - api_paths)  # 管理口未接前端（提示）

    print(f"openapi paths: {len(raw_openapi)} (docs/26 口径基线 219, 时点 Q371)")
    print(f"lib/api.ts 引用路径模板: {len(api_paths)}")
    if missing:
        print(f"\n[FAIL] lib/api.ts 引用但 openapi 不存在的路径（前端调 404，真漂移）: {len(missing)}")
        for p in missing:
            print(f"  - {p}")
    else:
        print("[OK] lib/api.ts 无悬空引用（全部路径模板均存在于 openapi）")
    if unlinked:
        print(f"\n[INFO] openapi 管理口未被 lib/api.ts 引用（合法含「后端先于前端」）: {len(unlinked)}")
        for p in unlinked:
            print(f"  - {p}")

    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
