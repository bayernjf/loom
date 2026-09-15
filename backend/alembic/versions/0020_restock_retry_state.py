"""Q90 restock transient backoff: restock_retry_state cursor table.

Retry state for restock_auto signals (Q87) lives outside the append-only
skill_runs log: attempts/next_attempt_at are upserted here and deleted when
the signal succeeds or becomes terminal. Budget exhaustion resets at the UTC
day boundary and never escalates; upstream errors escalate after
LOOM_RESTOCK_BACKOFF_MAX_ATTEMPTS.

Revision ID: 0020_restock_retry_state
Revises: 0019_agent_api_keys
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_restock_retry_state"
down_revision: str | None = "0019_agent_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "restock_retry_state",
        sa.Column("request_id", sa.String(length=36), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reason", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_restock_retry_state_next_attempt_at",
        "restock_retry_state",
        ["next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_restock_retry_state_next_attempt_at", table_name="restock_retry_state"
    )
    op.drop_table("restock_retry_state")
