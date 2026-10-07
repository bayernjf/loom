"""Q308: Q43 pool-option dictionary carrier (docs/02:155, docs/10 §dict_management).

Table `pool_options` — one row per PCP pool, `options` is the list of allowed
values for that pool. The 17 pool keys are seeded from
`app/core/pool_options/seeds.py`, which re-exports pa_rules.WEIGHT_KEYS_17 (the
same tuple Q40's weight validator enforces) rather than restating it, so the
dictionary cannot drift away from the validator.

The option lists themselves are left empty on purpose: the ruling defines
"pool -> option list, configurable dictionary (CRUD + audit)" but gives no
candidate values for any pool, and inventing them would be inventing business
facts. Ops fills them through the admin surface.

Revision ID: 0052_pool_options
Revises: 0051_downgrade_actions
Create Date: 2026-10-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.pool_options.seeds import POOL_KEYS

revision: str = "0052_pool_options"
down_revision: str | None = "0051_downgrade_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    pool_options = op.create_table(
        "pool_options",
        sa.Column("pool", sa.String(32), primary_key=True),
        sa.Column("options", json_type, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_pool_options_status", "pool_options", ["status"])
    op.bulk_insert(
        pool_options,
        [{"pool": pool, "options": []} for pool in POOL_KEYS],
    )


def downgrade() -> None:
    op.drop_index("ix_pool_options_status", table_name="pool_options")
    op.drop_table("pool_options")
