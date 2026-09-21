"""Q151 SLA sweep PG row-level fencing: per-lock tick claim rows.

Adds sweep_tick_claims, one row per cyclic lock (e.g. loom:lock:sla-sweep),
recording the monotonic leader fencing token (Q133 LockLease.fence) currently
allowed to write SLA job results in that tick. The leader claims in a short
transaction at tick start and gates each job commit with a conditional UPDATE
(WHERE lock_name = :name AND fence = :token); a stale leader whose lock was
lost mid-job and whose claim was overtaken by a larger fence matches zero rows,
rolls the job back and aborts the remaining jobs.

The table is untouched when the distributed lock is disabled (fence is None),
so the V1 single-replica default behaviour is unchanged.

Revision ID: 0038_sweep_tick_claims
Revises: 0037_restock_claims
Create Date: 2026-09-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0038_sweep_tick_claims"
down_revision: str | None = "0037_restock_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sweep_tick_claims",
        sa.Column("lock_name", sa.String(64), primary_key=True),
        sa.Column("fence", sa.Integer, nullable=False),
        sa.Column("claimed_by", sa.String(64), nullable=True),
        sa.Column(
            "claimed_at",
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


def downgrade() -> None:
    op.drop_table("sweep_tick_claims")
