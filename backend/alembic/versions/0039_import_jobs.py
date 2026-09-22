"""Q161 customer effect backfill async import jobs.

Mirrors the Q137 export_jobs task table for the write side:
- New table import_jobs records each batch backfill import request (CSV text or
  Excel .xlsx base64) with its carrier, result status, receipt counters and, on
  deterministic validation failure, the truncated per-row errors as JSON.
- Unlike exports, the input payload IS stored (Text): an import is a write that
  must be replayable by the background worker, whereas exports re-render from
  parameters at download time.
- V1 (import worker disabled) executes the import synchronously inside the
  request and lands the job in a terminal state; enabling the Redis Streams
  ImportWorker queues it as queued -> running -> completed/failed.

Revision ID: 0039_import_jobs
Revises: 0038_sweep_tick_claims
Create Date: 2026-09-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0039_import_jobs"
down_revision: str | None = "0038_sweep_tick_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("content_id", sa.String(36), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("filename", sa.String(128), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="completed",
        ),
        sa.Column("received", sa.Integer, nullable=False, server_default="0"),
        sa.Column("matched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("orphan", sa.Integer, nullable=False, server_default="0"),
        sa.Column("upserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("row_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("errors", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_import_jobs_tenant_id", "import_jobs", ["tenant_id"])
    op.create_index("ix_import_jobs_content_id", "import_jobs", ["content_id"])


def downgrade() -> None:
    op.drop_index("ix_import_jobs_content_id", table_name="import_jobs")
    op.drop_index("ix_import_jobs_tenant_id", table_name="import_jobs")
    op.drop_table("import_jobs")
