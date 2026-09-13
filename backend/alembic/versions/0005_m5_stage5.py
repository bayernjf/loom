"""M5 stage-5 PWC: contentGoals dictionary (Q25), pool config (Q27),
condition packages + combo items + usage records + per-platform states (Q21-Q24/Q71)

Revision ID: 0005_m5_stage5
Revises: 0004_m4_stage4
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_m5_stage5"
down_revision: str | None = "0004_m4_stage4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    content_goals = op.create_table(
        "content_goals",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("color", sa.String(16), nullable=True),
        sa.Column("ratio_min", sa.Float(), nullable=True),
        sa.Column("ratio_max", sa.Float(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
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
    # Q25 五类标准枚举（line 1090）；颜色/配比上下限原文未给值，留空待运营维护。
    op.bulk_insert(
        content_goals,
        [{"code": code} for code in (
            "ENGAGEMENT", "CONVERSION", "EDUCATION", "TRUST", "RETENTION"
        )],
    )

    op.create_table(
        "pwc_pool_configs",
        sa.Column(
            "product_space_id",
            sa.String(36),
            sa.ForeignKey("product_spaces.product_space_id"),
            primary_key=True,
        ),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("target_platforms", json_type, nullable=False),
        sa.Column("high_reuse_n", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "condition_packages",
        sa.Column("pwc_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "product_space_id",
            sa.String(36),
            sa.ForeignKey("product_spaces.product_space_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("goals", json_type, nullable=False),
        sa.Column("strategy_refs", json_type, nullable=False),
        sa.Column("structure_refs", json_type, nullable=False),
        sa.Column("expression_refs", json_type, nullable=False),
        sa.Column("compliance_result", json_type, nullable=False),
        sa.Column("score", sa.Float(), nullable=True, index=True),
        sa.Column("score_detail", json_type, nullable=False),
        sa.Column("score_incomplete", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column(
            "dup_of",
            sa.String(36),
            sa.ForeignKey("condition_packages.pwc_id"),
            nullable=True,
        ),
        sa.Column("is_backup", sa.Boolean(), nullable=False),
        sa.Column("gate_status", sa.String(8), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("high_reuse", sa.Boolean(), nullable=False),
        sa.Column("is_hot", sa.Boolean(), nullable=False),
        sa.Column("hot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by", sa.String(64), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "pwc_combo_items",
        sa.Column("item_id", sa.String(36), primary_key=True),
        sa.Column(
            "pwc_id",
            sa.String(36),
            sa.ForeignKey("condition_packages.pwc_id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "atom_id",
            sa.String(36),
            sa.ForeignKey("product_atom_instances.atom_id"),
            nullable=False,
        ),
        sa.Column("dimension_id", sa.String(36), nullable=True),
        sa.Column("fid", sa.String(64), nullable=True),
        sa.UniqueConstraint("pwc_id", "atom_id", name="uq_pwc_combo_atom"),
    )

    op.create_table(
        "pwc_usage_records",
        sa.Column("record_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "pwc_id",
            sa.String(36),
            sa.ForeignKey("condition_packages.pwc_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("platform", sa.String(32), nullable=False, index=True),
        sa.Column("account", sa.String(128), nullable=False),
        sa.Column("slot", sa.String(64), nullable=False),
        sa.Column("used_by", sa.String(64), nullable=True),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
        sa.UniqueConstraint(
            "pwc_id",
            "platform",
            "account",
            "slot",
            name="uq_pwc_usage_platform_account_slot",
        ),
    )

    op.create_table(
        "pwc_platform_states",
        sa.Column("state_id", sa.String(36), primary_key=True),
        sa.Column(
            "pwc_id",
            sa.String(36),
            sa.ForeignKey("condition_packages.pwc_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("pwc_id", "platform", name="uq_pwc_platform_state"),
    )


def downgrade() -> None:
    op.drop_table("pwc_platform_states")
    op.drop_table("pwc_usage_records")
    op.drop_table("pwc_combo_items")
    op.drop_table("condition_packages")
    op.drop_table("pwc_pool_configs")
    op.drop_table("content_goals")
