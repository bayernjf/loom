"""M4 stage-4 atoms: compliance wordlist (Q48), atom batches/candidates/conflicts,
product atom instances

Revision ID: 0004_m4_stage4
Revises: 0003_m3_stage3
Create Date: 2026-09-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_m4_stage4"
down_revision: str | None = "0003_m3_stage3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "compliance_wordlist",
        sa.Column("entry_id", sa.String(36), primary_key=True),
        sa.Column("word", sa.String(128), nullable=False, index=True),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("downgrade_target", sa.String(128), nullable=True),
        sa.Column("country", sa.String(8), nullable=True, index=True),
        sa.Column("industry", sa.String(64), nullable=True, index=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("created_by", sa.String(64), nullable=True),
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

    op.create_table(
        "atom_batches",
        sa.Column("batch_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "product_space_id",
            sa.String(36),
            sa.ForeignKey("product_spaces.product_space_id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "pool_id", sa.String(36), sa.ForeignKey("field_pools.pool_id"), nullable=False
        ),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("sensitive_snapshot", sa.Boolean(), nullable=False),
        sa.Column("submitted_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "atom_candidates",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("atom_batches.batch_id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "product_space_id",
            sa.String(36),
            sa.ForeignKey("product_spaces.product_space_id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "pool_id", sa.String(36), sa.ForeignKey("field_pools.pool_id"), nullable=False,
            index=True,
        ),
        sa.Column("dimension_id", sa.String(36), nullable=True, index=True),
        sa.Column("fid", sa.String(64), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("normalized", sa.String(512), nullable=False),
        sa.Column("fact_type", sa.String(16), nullable=True, index=True),
        sa.Column("risk_level", sa.String(8), nullable=False, index=True),
        sa.Column("risk_source", sa.String(16), nullable=False),
        sa.Column("matched_words", json_type, nullable=False),
        sa.Column("affinity", sa.Float(), nullable=True),
        sa.Column("low_affinity", sa.Boolean(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("evidence_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cluster_id", sa.String(36), nullable=True, index=True),
        sa.Column("aliases", json_type, nullable=False),
        sa.Column("alias_of", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.String(64), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("approved_atom_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("batch_id", "normalized", name="uq_atom_candidate_batch_dedup"),
    )

    op.create_table(
        "atom_conflicts",
        sa.Column("conflict_id", sa.String(36), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("atom_candidates.candidate_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("detail", json_type, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "product_atom_instances",
        sa.Column("atom_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "product_space_id",
            sa.String(36),
            sa.ForeignKey("product_spaces.product_space_id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "pool_id", sa.String(36), sa.ForeignKey("field_pools.pool_id"), nullable=False,
            index=True,
        ),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("atom_candidates.candidate_id"),
            nullable=False,
        ),
        sa.Column("dimension_id", sa.String(36), nullable=True),
        sa.Column("fid", sa.String(64), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("normalized", sa.String(512), nullable=False),
        sa.Column("fact_type", sa.String(16), nullable=True, index=True),
        sa.Column("aliases", json_type, nullable=False),
        sa.Column("risk_level", sa.String(8), nullable=False),
        sa.Column("risk_source", sa.String(16), nullable=False),
        sa.Column("affinity", sa.Float(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("reference_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("fact_type", "normalized", name="uq_product_fact_atom_value"),
    )


def downgrade() -> None:
    op.drop_table("product_atom_instances")
    op.drop_table("atom_conflicts")
    op.drop_table("atom_candidates")
    op.drop_table("atom_batches")
    op.drop_table("compliance_wordlist")
