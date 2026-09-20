"""Q126 segment-13 effect-callback ingestion: effect_records time-series table.

First slice of the segment-13 feedback loop (contract in docs/05 §1.1.1 /
docs/11 §2.1, Q60). External Agents push effect metrics to
POST /api/effect-callback (Bearer Agent Key, Q88). Records are a time series
keyed idempotently by (external_content_id, captured_at): a re-push of the same
point overwrites, a new captured_at appends. Records that do not match a live
content_products row land in status='orphan' for manual claim (Q60a, later
slice). metrics is a sparse JSONB; absent keys are never stored as zero.

matched_content_id is a nullable FK to content_products; the composite series
index covers single-column lookups via its left prefix.

Revision ID: 0034_effect_records
Revises: 0033_content_publish
Create Date: 2026-09-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0034_effect_records"
down_revision: str | None = "0033_content_publish"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "effect_records",
        sa.Column("record_id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("external_content_id", sa.String(36), nullable=False),
        sa.Column("matched_content_id", sa.String(36), nullable=True),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("platform_post_id", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", json_type, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="orphan"),
        sa.Column("received_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["matched_content_id"],
            ["content_products.content_id"],
            name="fk_effect_records_content",
        ),
    )
    op.create_index(
        "uq_effect_content_captured",
        "effect_records",
        ["external_content_id", "captured_at"],
        unique=True,
    )
    op.create_index(
        "ix_effect_records_status", "effect_records", ["status"]
    )
    op.create_index(
        "ix_effect_records_matched_series",
        "effect_records",
        ["matched_content_id", "captured_at"],
    )
    op.create_index("ix_effect_records_tenant_id", "effect_records", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_effect_records_tenant_id", table_name="effect_records")
    op.drop_index("ix_effect_records_matched_series", table_name="effect_records")
    op.drop_index("ix_effect_records_status", table_name="effect_records")
    op.drop_index("uq_effect_content_captured", table_name="effect_records")
    op.drop_table("effect_records")
