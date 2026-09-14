"""M6 stage-6 PWS freeze: immutable snapshots, snapshot items, freeze logs (Q28-Q33)

Revision ID: 0006_m6_stage6
Revises: 0005_m5_stage5
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_m6_stage6"
down_revision: str | None = "0005_m5_stage5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "pws_snapshots",
        sa.Column("pws_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "product_space_id",
            sa.String(36),
            sa.ForeignKey("product_spaces.product_space_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, index=True),
        sa.Column("pool_id", sa.String(36), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, index=True),
        sa.Column("snapshot", json_type, nullable=False),
        sa.Column("readiness", json_type, nullable=False),
        sa.Column("refreeze_tier", sa.String(16), nullable=True),
        sa.Column("reason_code", sa.String(48), nullable=True),
        sa.Column("superseded_by", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_by", sa.String(64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("product_space_id", "version", name="uq_pws_ps_version"),
    )

    op.create_table(
        "pws_snapshot_items",
        sa.Column("item_id", sa.String(36), primary_key=True),
        sa.Column(
            "pws_id",
            sa.String(36),
            sa.ForeignKey("pws_snapshots.pws_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("ref_id", sa.String(36), nullable=False),
        sa.Column("dimension_id", sa.String(36), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.UniqueConstraint("pws_id", "kind", "ref_id", name="uq_pws_item_ref"),
    )

    op.create_table(
        "pws_freeze_logs",
        sa.Column("log_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("product_space_id", sa.String(36), nullable=False, index=True),
        sa.Column("pws_id", sa.String(36), nullable=True, index=True),
        sa.Column("event", sa.String(24), nullable=False),
        sa.Column("tier", sa.String(16), nullable=True),
        sa.Column("reason_code", sa.String(48), nullable=True),
        sa.Column("detail", json_type, nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("pws_freeze_logs")
    op.drop_table("pws_snapshot_items")
    op.drop_table("pws_snapshots")
