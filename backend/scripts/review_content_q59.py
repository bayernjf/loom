#!/usr/bin/env python3
"""Q59 ③④ 本地复检 CLI：对指定成稿重跑 CONTENT-COMPLIANCE 并落库 review_hits。

用法：
    cd backend
    .venv/bin/python scripts/review_content_q59.py --content-id <uuid>

口径（docs/29 v0.1 工程甲案）：③施工指令核对 / ④国家规则核对均为 advisory，
不阻断状态流转；本脚本只刷新 ``content_products.review_hits``，不动 status。
"""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import ContentProduct
from app.content.service import run_content_review
from app.core.config import get_settings


async def _main(args: argparse.Namespace) -> int:
    settings = get_settings()
    dsn = args.dsn or settings.database_dsn
    engine = create_async_engine(dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            content = await session.get(ContentProduct, args.content_id)
            if content is None:
                print(json.dumps({"error": "content_not_found"}, ensure_ascii=False))
                return 2
            hits = await run_content_review(session, content)
            content.review_hits = hits
            await session.commit()
            print(
                json.dumps(
                    {
                        "content_id": content.content_id,
                        "status": content.status,
                        "review_hits": hits,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                flush=True,
            )
            return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="rerun Q59 content review")
    parser.add_argument("--content-id", required=True)
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
