#!/usr/bin/env python3
"""P1-2 引导：签出首枚 staff 访问令牌，免去「先关闸、再签、再开闸」。

背景：``LOOM_STAFF_AUTH_ENABLED=true`` 且 ``staff_api_keys`` 没有 active 行时，后端
按设计 fail-fast（见 ``app/main.py::_assert_staff_credentials``）。旧引导路径要求运维
临时把门控关掉、调 ``POST /api/admin/staff-keys`` 自报签发、再开闸重启——三次改配置，
任何一步漏了都表现为全站 401。

本脚本直接写库（复用 ``staff_auth.service`` 的哈希、角色校验与审计），因此门控开着
也能签出首令牌；条件只有「库为空或门控关闭」。门控已开且已有 active 令牌时默认拒绝，
避免把引导脚本当成日常发证口（日常发证仍走 API，``--force`` 仅用于明确要再加一枚）。

明文只在标准输出出现一次，不写日志、不回库。

用法：
    cd backend
    python scripts/bootstrap_staff_key.py --staff-id <工号> --staff-name <姓名>

    # 库可直连但 settings 的 DSN 不对时显式指定
    python scripts/bootstrap_staff_key.py --staff-id ops-01 --staff-name 运营 \
        --dsn postgresql+asyncpg://...

    # 门控已开且已有 active 令牌，仍要追加一枚（明确意图时才用）
    python scripts/bootstrap_staff_key.py --staff-id ops-02 --staff-name 运营2 --force
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.actor import Actor
from app.core.config import get_settings
from app.core.rbac import PLATFORM_ADMIN
from app.core.staff_auth import service
from app.core.staff_auth.models import StaffApiKey

# 审计里区分「引导脚本」与 API 自报签发；created_by 同样记这个稳定标识。
BOOTSTRAP_ACTOR_ID = "bootstrap-script"


class BootstrapRefused(Exception):
    """脚本拒绝签发：不是缺参数，而是当前状态不该再签（已引导过）。"""


async def active_staff_key_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(StaffApiKey).where(StaffApiKey.status == "active")
        )
        or 0
    )


async def bootstrap_staff_key(
    *,
    dsn: str,
    staff_id: str,
    staff_name: str,
    roles: list[str],
    gate_enabled: bool,
    force: bool = False,
) -> tuple[StaffApiKey, str]:
    """签发一枚 active 令牌并返回 ``(行, 明文)``；明文只应打印一次。

    允许的两种状态：门控关闭（引导期），或库内没有 active 令牌（后端正因此起不来）。
    门控开启且已有 active 令牌时拒绝，除非 ``force``。
    """
    engine = create_async_engine(dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            active = await active_staff_key_count(session)
            if gate_enabled and active and not force:
                raise BootstrapRefused(
                    f"staff authentication is already bootstrapped ({active} active token(s)); "
                    "issue additional keys through POST /api/admin/staff-keys, or pass --force "
                    "if you really mean to add another bootstrap token."
                )
            row, plaintext = await service.issue_staff_key(
                session,
                staff_id=staff_id,
                staff_name=staff_name,
                roles=roles,
                actor=Actor(id=BOOTSTRAP_ACTOR_ID, roles=[PLATFORM_ADMIN]),
            )
            await session.commit()
            return row, plaintext
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staff-id", required=True, help="人员稳定标识（工号/登录名）")
    parser.add_argument("--staff-name", required=True, help="显示名")
    parser.add_argument(
        "--role",
        action="append",
        default=None,
        help="绑定内部角色（可多次，默认 platform_admin）",
    )
    parser.add_argument("--dsn", default=None, help="async DSN（缺省取 settings）")
    parser.add_argument(
        "--force",
        action="store_true",
        help="门控已开且已有 active 令牌时仍追加一枚",
    )
    args = parser.parse_args()

    settings = get_settings()
    roles = args.role or [PLATFORM_ADMIN]
    try:
        row, plaintext = asyncio.run(
            bootstrap_staff_key(
                dsn=args.dsn or settings.database_dsn,
                staff_id=args.staff_id,
                staff_name=args.staff_name,
                roles=roles,
                gate_enabled=settings.staff_auth_enabled,
                force=args.force,
            )
        )
    except BootstrapRefused as exc:
        print(f"[REFUSED] {exc}", file=sys.stderr)
        return 2
    except (ValueError, SQLAlchemyError, OSError) as exc:
        # 库不可达 / 迁移未跑 / 角色非法：都要求人看懂下一步，而不是只看到 traceback。
        print(f"[FAILED] {exc.__class__.__name__}: {exc}", file=sys.stderr)
        print(
            "Next: check the database is reachable and migrations ran "
            "(`alembic upgrade head`), and that --role is an internal role.",
            file=sys.stderr,
        )
        return 1

    print("Staff access token (plaintext is shown once; store it now):")
    print(f"  {plaintext}")
    print(
        f"\nkey_id={row.key_id} prefix={row.key_prefix} staff_id={row.staff_id} "
        f"roles={list(row.roles)} status={row.status}"
    )
    print(
        "Next: paste this token into /admin/login (it calls /api/auth/me), then restart "
        "the backend with LOOM_STAFF_AUTH_ENABLED=true."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
