import asyncio
import os
from logging.config import fileConfig

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from alembic import context
from app.core import models as _core_models  # noqa: F401  (register audit_logs)
from app.core.compliance_wordlist import models as _wordlist_models  # noqa: F401
from app.core.config_center import models as _config_models  # noqa: F401
from app.core.db import Base
from app.core.staff_auth import models as _staff_auth_models  # noqa: F401
from app.decision.compliance_center import models as _ccr_models  # noqa: F401
from app.decision.layer_strategy import models as _package_models  # noqa: F401
from app.final.final_whitelist import models as _fcw_models  # noqa: F401
from app.platform.platform_adaptation import models as _platform_models  # noqa: F401
from app.product.atom import models as _atom_models  # noqa: F401
from app.product.condition import models as _condition_models  # noqa: F401
from app.product.fieldpool import models as _fieldpool_models  # noqa: F401
from app.product.modeling import models as _modeling_models  # noqa: F401
from app.product.product_intake import models as _models  # noqa: F401  (register tables)
from app.product.whitelist_center import models as _whitelist_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Secrets/DSN only via environment (docs/15 §4); no credentials in the repo.
database_dsn = os.environ.get(
    "LOOM_DATABASE_DSN",
    "postgresql+asyncpg://loom:loom@localhost:5432/loom",
)
config.set_main_option("sqlalchemy.url", database_dsn)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _ensure_version_table(connection) -> None:
    # Q118：revision id 自 0021 起最长 33 字符，超过 Alembic 默认版本表
    # version_num VARCHAR(32)，全新库全链 upgrade 会在 0021 处截断报错。
    # 在独立事务里预置/加宽版本表（alembic 建表 checkfirst=True，存在即复用），
    # 避免 DDL 混入迁移事务破坏 alembic 的提交边界。
    connection.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(128) NOT NULL PRIMARY KEY)"
        )
    )
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text(
                "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"
            )
        )


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


# Q157：多副本（>=2 backend）同时启动会并发跑 `alembic upgrade head`，在全新库
# 上竞争 DDL 与 alembic_version 写入。用一个固定的 PG session 级咨询锁把迁移
# 串行化：第一个副本拿锁跑完升级并释放，其余副本阻塞获锁后跑到 head 即 no-op。
# 仅 PostgreSQL 生效；其他方言（本地 sqlite 不经此入口）保持原行为。key 为
# "LOOM" 四字符 ASCII（0x4C4F4F4D）。NullPool 下持锁连接是独立物理连接，
# session 级锁随该连接关闭释放，这里仍显式 unlock 以求确定。
MIGRATION_ADVISORY_LOCK_KEY = 0x4C4F4F4D


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as lock_connection:
        use_advisory_lock = lock_connection.dialect.name == "postgresql"
        if use_advisory_lock:
            await lock_connection.execute(
                sa.text("SELECT pg_advisory_lock(:key)"),
                {"key": MIGRATION_ADVISORY_LOCK_KEY},
            )
            await lock_connection.commit()  # 提交取锁事务；session 级锁继续持有
        try:
            async with connectable.begin() as connection:
                await connection.run_sync(_ensure_version_table)
            async with connectable.connect() as connection:
                await connection.run_sync(do_run_migrations)
        finally:
            if use_advisory_lock:
                await lock_connection.execute(
                    sa.text("SELECT pg_advisory_unlock(:key)"),
                    {"key": MIGRATION_ADVISORY_LOCK_KEY},
                )
                await lock_connection.commit()
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
