"""M11 stage-7/8 static base tables: publish slots, platform rules, slot-type
defaults, goal fit weights, PCP templates/weight tables, stage-9 packages (Q34-Q40/Q45/Q52)

Revision ID: 0008_m11_stage78
Revises: 0007_m7_stage10
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.platform.platform_adaptation.seeds import FIT_WEIGHT_SEEDS, PCP_TEMPLATE_SEEDS

revision: str = "0008_m11_stage78"
down_revision: str | None = "0007_m7_stage10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "publish_slots",
        sa.Column("slot_id", sa.String(36), primary_key=True),
        sa.Column("platform", sa.String(32), nullable=False, index=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slot_type", sa.String(32), nullable=False, index=True),
        sa.Column("chars_max", sa.Integer(), nullable=True),
        sa.Column("dur_min", sa.Integer(), nullable=True),
        sa.Column("dur_max", sa.Integer(), nullable=True),
        sa.Column("traffic", sa.Float(), nullable=False, server_default="0"),
        sa.Column("safe", sa.Float(), nullable=False, server_default="0"),
        sa.Column("conv", sa.Float(), nullable=False, server_default="0"),
        sa.Column("load", sa.Float(), nullable=False, server_default="0"),
        sa.Column("score_source", sa.String(16), nullable=False, server_default="manual_eval"),
        sa.Column("risk", sa.String(16), nullable=True),
        sa.Column("gate", sa.String(16), nullable=False, server_default="approved"),
        sa.Column("source_url", sa.String(512), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "goal_fit_weights",
        sa.Column("goal", sa.String(32), primary_key=True),
        sa.Column("weights", json_type, nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.bulk_insert(
        sa.table(
            "goal_fit_weights",
            sa.column("goal", sa.String),
            sa.column("weights", json_type),
        ),
        FIT_WEIGHT_SEEDS,
    )

    op.create_table(
        "platform_rules",
        sa.Column("rule_id", sa.String(36), primary_key=True),
        sa.Column("selector_level", sa.String(24), nullable=False, index=True),
        sa.Column("platform", sa.String(32), nullable=True, index=True),
        sa.Column("slot_type", sa.String(32), nullable=True, index=True),
        sa.Column("slot_id", sa.String(36), nullable=True, index=True),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column("effect", sa.String(16), nullable=False),
        sa.Column("note", sa.String(512), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "slot_type_defaults",
        sa.Column("slot_type", sa.String(32), primary_key=True),
        sa.Column("daily_limit_min", sa.Integer(), nullable=True),
        sa.Column("daily_limit_max", sa.Integer(), nullable=True),
        sa.Column("defaults", json_type, nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "pcp_templates",
        sa.Column("template_id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("weights", json_type, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "pcp_templates",
            sa.column("template_id", sa.String),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("weights", json_type),
        ),
        PCP_TEMPLATE_SEEDS,
    )

    op.create_table(
        "pcp_weight_tables",
        sa.Column("pcp_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("product_space_id", sa.String(36), nullable=False, index=True),
        sa.Column("platform", sa.String(32), nullable=False, index=True),
        sa.Column("template_code", sa.String(32), nullable=True),
        sa.Column("weights", json_type, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("product_space_id", "platform", name="uq_pcp_ps_platform"),
    )

    op.create_table(
        "packages",
        sa.Column("package_id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(8), nullable=False, index=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("product_space_id", sa.String(36), nullable=False, index=True),
        sa.Column("platform", sa.String(32), nullable=False, index=True),
        sa.Column("goal", sa.String(32), nullable=False, index=True),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("conf", sa.Float(), nullable=True),
        sa.Column("gate", sa.String(16), nullable=False, server_default="approved"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("packages")
    op.drop_table("pcp_weight_tables")
    op.drop_table("pcp_templates")
    op.drop_table("slot_type_defaults")
    op.drop_table("platform_rules")
    op.drop_table("goal_fit_weights")
    op.drop_table("publish_slots")
