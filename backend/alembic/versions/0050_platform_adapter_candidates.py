"""Q300: PLATFORM-ADAPTER candidates + HumanGate (design-v2-platform-adapter §3.2 乙).

New platform_adapter_candidates table, modelled on pcp_recalc_candidates (0045):
- AI/synthetic produces four-state advisory candidates; ops approves/rejects.
- approve only resolves pending + leaves an audit trail — it never writes rules,
  never blocks a certificate, never touches final_id (PT constraints 4/6).
- partial unique index: one pending candidate per
  (pws_snapshot_id, platform, slot_type, slot_id). slot_id is nullable, so a
  coalesced empty-string column is part of the index key (dual where, same as
  uq_pcp_recalc_pending).

Revision ID: 0050_platform_adapter_candidates
Revises: 0049_pcp_weekly_recalc_seed
Create Date: 2026-10-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0050_platform_adapter_candidates"
down_revision: str | None = "0049_pcp_weekly_recalc_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "platform_adapter_candidates",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("pws_snapshot_id", sa.String(36), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("slot_type", sa.String(32), nullable=False),
        sa.Column("slot_id", sa.String(36), nullable=True),
        sa.Column("coalesce_slot_id", sa.String(36), nullable=False),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(24), nullable=True),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.Column("refs", json_type, nullable=False),
        sa.Column("missing", sa.Boolean, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rejected_reason", sa.String(512), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.String(64), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_platform_adapter_candidates_pws",
        "platform_adapter_candidates",
        ["pws_snapshot_id"],
    )
    op.create_index(
        "ix_platform_adapter_candidates_status",
        "platform_adapter_candidates",
        ["status"],
    )
    op.create_index(
        "uq_platform_adapter_pending",
        "platform_adapter_candidates",
        ["pws_snapshot_id", "platform", "slot_type", "coalesce_slot_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_platform_adapter_pending", table_name="platform_adapter_candidates")
    op.drop_index("ix_platform_adapter_candidates_status", table_name="platform_adapter_candidates")
    op.drop_index("ix_platform_adapter_candidates_pws", table_name="platform_adapter_candidates")
    op.drop_table("platform_adapter_candidates")
