#!/usr/bin/env python3
"""Q372：E2E 清单脚本化（API 级冒烟，docs/26 核心判据的可重跑版本）。

docs/26《新用户E2E验证清单》的两轮实测（Q369/Q371）证明核心闭环判据集中在
**API 级**：E1.1 幂等唯一出口 409、Guard 材料拦截 409、配置中心热更、令牌在场、
openapi paths 基线。浏览器部分（页面渲染/UI 状态）仍按 docs/26 现场执行；本脚本
把 API 级判据变成可重跑冒烟，供 E2E 前后一致性核对。

**只读 + 零副作用设计**：
- publish 同组合只用于触发「幂等 409」——409 发生在校验期，不写库（实测确认）；
- 配置中心只 GET 不 PUT（热更写口 E2E 时人工做）；
- 不做任何 revoke / 新建 / 修改。

用法：
    python scripts/smoke_e2e_api.py --base http://localhost:8000 --token <PAT>
        [--assemble-body '<JSON>'] [--json]
--assemble-body 传 E1.1 幂等核对用的完整重发参数（已存在组合），断言必 409；
不传则该项跳过（浏览器 E2E 时用真实组合核对）。退出码：全部断言通过 0；
任一失败 1。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

MIN_OPENAPI_PATHS = 219  # Q368 形态基线（docs/26 口径）
# docs/26 §6.4：E2E 三令牌 key_id 前缀（在场核对）
E2E_KEY_PREFIXES = ("17be1f4a", "32e4ecf2", "09cdeafe")


def _request(base: str, path: str, token: str | None,
             method: str = "GET", body: dict | None = None):
    url = f"{base.rstrip('/')}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--token", required=True, help="platform_admin 令牌明文")
    parser.add_argument(
        "--assemble-body",
        default=None,
        help="E1.1 幂等核对用完整重发参数（POST /api/fcw/assemble 的 body JSON，"
             "取 docs/26 §6.2 已存在组合；提供则断言必 409 且 detail 含 "
             "'already issued'，不提供则跳过该项）",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    checks: list[dict] = []
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            failures.append(f"{name}: {detail}")

    # 1. 健康检查（无鉴权）
    code, body = _request(args.base, "/healthz", None)
    check("healthz", code == 200, f"HTTP {code}")

    # 2. openapi paths 基线（无鉴权，网关外）
    code, body = _request(args.base, "/openapi.json", None)
    paths = len(body.get("paths", {})) if isinstance(body, dict) else 0
    check("openapi paths ≥ 219", code == 200 and paths >= MIN_OPENAPI_PATHS,
          f"HTTP {code}, paths={paths}")

    # 3. staff-keys 只读：E2E 三令牌在场（docs/26 §6.4）
    code, body = _request(
        args.base, "/api/admin/staff-keys?include_revoked=true", args.token)
    if code == 200 and isinstance(body, list):
        keys = {r.get("key_id", "")[:8] for r in body}
        missing = [p for p in E2E_KEY_PREFIXES if not any(k.startswith(p) for k in keys)]
        check("E2E 令牌在场", not missing,
              f"missing prefixes={missing or '无'}, total={len(body)}")
    else:
        check("E2E 令牌在场", False, f"HTTP {code}")

    # 4. 配置中心只读：content.regen_limit 存在（Q56/Q364）
    code, body = _request(
        args.base, "/api/admin/config/content.regen_limit", args.token)
    ok = code == 200 and isinstance(body, dict) and body.get("key") == "content.regen_limit"
    check("config content.regen_limit", ok,
          f"HTTP {code}, value={body.get('value') if isinstance(body, dict) else body}")

    # 5. E1.1 幂等唯一出口（docs/26 §6.2，零副作用；可选核对）
    if args.assemble_body:
        try:
            body = json.loads(args.assemble_body)
        except json.JSONDecodeError as exc:
            check("E1.1 幂等 409", False, f"--assemble-body 非法 JSON: {exc}")
            body = None
        if body is not None:
            code, resp = _request(args.base, "/api/fcw/assemble", args.token,
                                  method="POST", body=body)
            detail = resp.get("detail") if isinstance(resp, dict) else resp
            check("E1.1 幂等 409", code == 409 and "already issued" in str(detail),
                  f"HTTP {code}, detail={detail}")
    else:
        checks.append({"name": "E1.1 幂等 409", "ok": True,
                       "detail": "跳过（未传 --assemble-body；E2E 时用真实组合参数核对）"})

    if args.json:
        print(json.dumps({"checks": checks, "failures": failures},
                         ensure_ascii=False, indent=2))
    else:
        for c in checks:
            print(f"  [{'OK' if c['ok'] else 'FAIL'}] {c['name']} — {c['detail']}")
        if failures:
            print(f"\n[FAIL] {len(failures)} 项未通过（Q372 smoke_e2e_api）")
        else:
            print(f"\n[OK] {len(checks)} 项全部通过（Q372 smoke_e2e_api）")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
