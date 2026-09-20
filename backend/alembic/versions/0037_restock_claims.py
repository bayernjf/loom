"""Q143 restock PG row-level fencing: per-request claim rows.

Adds restock_claims, one row per requested restock signal, recording the
monotonic leader fencing token (Q133 LockLease.fence) currently allowed to
spend on it. The leader claims in a short transaction before the model call
and gates the success-result commit with a conditional UPDATE
(WHERE request_id = :id AND fence = :token); a stale leader whose lock was
lost mid-spend and whose claim was overtaken by a larger fence matches zero
rows and rolls back, so duplicate candidates/child runs are never written.

The table is untouched when the distributed lock is disabled (fence is None),
so the V1 single-replica default behaviour is unchanged.

Revision ID: 0037_restock_claims
Revises: 0036_export_jobs
Create Date: 2026-09-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0037_restock_claims"
down_revision: str | None = "0036_export_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "restock_claims",
        sa.Column("request_id", sa.String(36), primary_key=True),
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
    op.drop_table("restock_claims")
