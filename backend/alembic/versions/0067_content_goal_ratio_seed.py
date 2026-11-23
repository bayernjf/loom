"""Q44: seed the five content-goal ratio bounds from PRD line 1090.

Pure data seed (no schema change). ``content_goals.ratio_min/ratio_max`` existed
since 0005 but were intentionally left NULL because the PRD gives only one
bound per goal. Q44 now consumes them as a soft prompt, so seed the exact
single-sided bounds; operations can still retune them via the Q25 dictionary
write endpoint.

ON CONFLICT-style discipline: only rows whose *both* bounds are still NULL are
updated, so a partially/fully configured goal is never overwritten. Downgrade
deletes the values only when the full two-column fingerprint still matches the
seed (0057/Q351 rule), preserving operations edits.

Revision ID: 0067_content_goal_ratio_seed
Revises: 0066_client_access_tokens
Create Date: 2026-11-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.product.condition.seeds import CONTENT_GOAL_RATIO_DEFAULTS

revision: str = "0067_content_goal_ratio_seed"
down_revision: str | None = "0066_client_access_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _content_goals_table():
    return sa.table(
        "content_goals",
        sa.column("code", sa.String),
        sa.column("ratio_min", sa.Float),
        sa.column("ratio_max", sa.Float),
    )


def upgrade() -> None:
    bind = op.get_bind()
    goals = _content_goals_table()
    for code, (ratio_min, ratio_max) in CONTENT_GOAL_RATIO_DEFAULTS.items():
        bind.execute(
            sa.update(goals)
            .where(
                goals.c.code == code,
                goals.c.ratio_min.is_(None),
                goals.c.ratio_max.is_(None),
            )
            .values(ratio_min=ratio_min, ratio_max=ratio_max)
        )


def downgrade() -> None:
    bind = op.get_bind()
    goals = _content_goals_table()
    for code, (ratio_min, ratio_max) in CONTENT_GOAL_RATIO_DEFAULTS.items():
        bind.execute(
            sa.update(goals)
            .where(
                goals.c.code == code,
                goals.c.ratio_min == ratio_min,
                goals.c.ratio_max == ratio_max,
            )
            .values(ratio_min=None, ratio_max=None)
        )
