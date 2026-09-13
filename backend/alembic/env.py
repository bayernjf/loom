import asyncio
import os
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from alembic import context
from app.core import models as _core_models  # noqa: F401  (register audit_logs)
from app.core.db import Base
from app.product.modeling import models as _modeling_models  # noqa: F401
from app.product.product_intake import models as _models  # noqa: F401  (register tables)

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


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
