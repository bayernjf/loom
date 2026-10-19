#!/usr/bin/env python3
"""Q372：staff_api_keys 运维脚本——只读列出 + 走 API 吊销（审计留痕）。

背景：E2E 轮（Q369/Q371）签发过 e2e-verifier / e2e-ops / e2e-ops-r2 三枚测试令牌
（docs/26 §6.4）。上线前应吊销测试令牌；吊销必须走 `POST /api/admin/staff-keys/
{key_id}/revoke`（Q178 服务层硬闸 platform_admin，审计 append-only），**禁止直写
DB**。

子命令：
    revoke_staff_keys.py list [--dsn DSN] [--json]
        只读列出全部 staff_api_keys（含已吊销），供审计核对。DSN 取
        LOOM_DATABASE_DSN，缺省用 app.core.config.get_settings().database_dsn。

    revoke_staff_keys.py revoke --key-id <id> [--key-id <id>...]
        --token <PAT> [--base http://localhost:8000] [--actor-id <id>]
        逐个调用 revoke 端点（Bearer=<PAT>，需 platform_admin）。body.actor
        仅作审计占位（后端权限以 Bearer 令牌为准）。失败即停（不静默跳过）。

示例：
    python scripts/revoke_staff_keys.py list --json
    python scripts/revoke_staff_keys.py revoke \
        --key-id 09cdeafe-cbc6-11f1-a1c5-0e6f757b906c --token <PAT>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.staff_auth.models import StaffApiKey


def _dsn(args_dsn: str | None) -> str:
    if args_dsn:
        return args_dsn
    return get_settings().database_dsn


async def do_list(dsn: str, as_json: bool) -> int:
    engine = create_async_engine(dsn)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(StaffApiKey).order_by(StaffApiKey.created_at.desc())
            )
        ).scalars().all()
    await engine.dispose()
    records = [
        {
            "key_id": r.key_id,
            "staff_id": r.staff_id,
            "staff_name": r.staff_name,
            "roles": r.roles,
            "key_prefix": r.key_prefix,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
        }
        for r in rows
    ]
    if as_json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        active = [r for r in records if r["status"] == "active"]
        revoked = [r for r in records if r["status"] != "active"]
        print(f"staff_api_keys: {len(records)} total "
              f"({len(active)} active / {len(revoked)} revoked)")
        for r in records:
            print(
                f"  {r['status']:<8} {r['key_id']}  "
                f"{r['staff_name']}({r['staff_id']}) roles={r['roles']} "
                f"prefix={r['key_prefix']} created={r['created_at']}"
            )
        if active:
            print("\n# 吊销清单（按需）——须提供一枚 platform_admin 令牌明文：")
            for r in active:
                print(f"  --key-id {r['key_id']}")
    return 0


def do_revoke(
    key_ids: list[str],
    token: str,
    base: str,
    actor_id: str,
) -> int:
    import urllib.error

    failures = 0
    for kid in key_ids:
        url = f"{base.rstrip('/')}/api/admin/staff-keys/{kid}/revoke"
        body = json.dumps({"actor": {"id": actor_id, "roles": ["platform_admin"]}}).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            print(f"[OK] revoked {kid} -> status={data.get('status')}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()
            print(f"[FAIL] revoke {kid}: HTTP {exc.code} {detail}", file=sys.stderr)
            failures += 1
        except OSError as exc:
            print(f"[FAIL] revoke {kid}: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="只读列出全部 staff_api_keys")
    p_list.add_argument("--dsn", default=None, help="async DSN（缺省取 settings）")
    p_list.add_argument("--json", action="store_true", help="JSON 输出")

    p_revoke = sub.add_parser("revoke", help="走 API 吊销（审计留痕，禁直写 DB）")
    p_revoke.add_argument("--key-id", action="append", required=True,
                          help="待吊销 key_id（可多次）")
    p_revoke.add_argument("--token", required=True,
                          help="调用方 platform_admin 令牌明文（Bearer）")
    p_revoke.add_argument("--base", default="http://localhost:8000",
                          help="后端地址（默认 http://localhost:8000）")
    p_revoke.add_argument("--actor-id", default="ops-script",
                          help="审计占位 actor.id（后端权限以 Bearer 为准）")

    args = parser.parse_args()
    if args.cmd == "list":
        return asyncio.run(do_list(_dsn(args.dsn), args.json))
    return do_revoke(args.key_id, args.token, args.base, args.actor_id)


if __name__ == "__main__":
    sys.exit(main())
