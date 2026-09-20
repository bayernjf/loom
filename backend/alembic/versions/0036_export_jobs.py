"""Q132 middleground export jobs: JSON form + async export task records.

Extends the Q100 synchronous final_id CSV export:
- New table export_jobs records each middleground export request with its
  parameters (tenant / optional product space / format) and result status.
- V1 executes the export synchronously inside the request and marks the job
  completed; queued/running background workers are deferred to V2
  (Redis Streams). Downloads re-render from the job parameters, so no file
  payload is stored and downloads stay idempotent.

Revision ID: 0036_export_jobs
Revises: 0035_effect_claims
Create Date: 2026-09-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0036_export_jobs"
down_revision: str | None = "0035_effect_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("product_space_id", sa.String(36), nullable=True),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="completed",
        ),
        sa.Column(
            "row_count", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column("file_name", sa.String(128), nullable=False),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_export_jobs_tenant_id", "export_jobs", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_export_jobs_tenant_id", table_name="export_jobs")
    op.drop_table("export_jobs")
