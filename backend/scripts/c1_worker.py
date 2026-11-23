#!/usr/bin/env python3
"""本机 C1 自动识别 worker CLI。

用法：
    cd backend
    .venv/bin/python scripts/c1_worker.py --once
    .venv/bin/python scripts/c1_worker.py --watch --interval 60

说明：
- 读 Settings 的 LOOM_DATABASE_DSN，也可用 --dsn 显式指定。
- 只消费 ai_recognizing 且没有 pending c1 候选的 intake；产出仍走人工 Gate。
- 常驻进程用 `nohup ... --watch` 或 launchd 托管；容器形态由 app.main 的
  LOOM_C1_WORKER_ENABLED 开关负责。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.model_registry.c1_worker import C1RecognitionWorker, run_c1_once


async def _main(args: argparse.Namespace) -> int:
    settings = get_settings()
    dsn = args.dsn or settings.database_dsn
    engine = create_async_engine(dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        if args.watch:
            worker = C1RecognitionWorker(factory, args.interval, args.limit)
            await worker.start()
            print(
                f"c1 worker watching (interval={args.interval}s, limit={args.limit})",
                flush=True,
            )
            await asyncio.Event().wait()
        report = await run_c1_once(factory, limit=args.limit)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return 1 if report["errors"] else 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Loom C1 auto-recognition worker")
    parser.add_argument("--once", action="store_true", help="run one sweep (default)")
    parser.add_argument("--watch", action="store_true", help="run continuously")
    parser.add_argument("--interval", type=float, default=60.0, help="watch interval seconds")
    parser.add_argument("--limit", type=int, default=10, help="max intakes per sweep")
    parser.add_argument("--dsn", default=None, help="override LOOM_DATABASE_DSN")
    args = parser.parse_args()
    if args.watch and args.once:
        parser.error("--once and --watch are mutually exclusive")
    if args.watch:
        args.once = False
    try:
        raise SystemExit(asyncio.run(_main(args)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
