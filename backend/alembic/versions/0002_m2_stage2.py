"""M2 stage-2 C1 recognition: signal weights, industry thresholds, C1 records,
ops todos, G1 category tree/templates, c7 runs, G2 field candidates

Revision ID: 0002_m2_stage2
Revises: 0001_m1_stage1
Create Date: 2026-09-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_m2_stage2"
down_revision: str | None = "0001_m1_stage1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

profile_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "c1_signal_weights",
        sa.Column("signal", sa.String(32), primary_key=True),
        sa.Column("signal_name", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("scoring_method", sa.String(128), nullable=True),
    )
    op.create_table(
        "c1_industry_thresholds",
        sa.Column("industry", sa.String(64), primary_key=True),
        sa.Column("keywords", profile_type, nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "c1_records",
        sa.Column("record_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "intake_id",
            sa.String(36),
            sa.ForeignKey("product_intake_applications.intake_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("signals", profile_type, nullable=False),
        sa.Column("conf", sa.Float(), nullable=False),
        sa.Column("industry", sa.String(64), nullable=False),
        sa.Column("branch", sa.String(32), nullable=False),
        sa.Column("top_candidates", profile_type, nullable=False),
        sa.Column("top_gap", sa.Float(), nullable=True),
        sa.Column("selected_category_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "ops_todos",
        sa.Column("todo_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("todo_type", sa.String(32), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("assignee_role", sa.String(32), nullable=False),
        sa.Column("detail", profile_type, nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "g1_categories",
        sa.Column("category_id", sa.String(36), primary_key=True),
        sa.Column(
            "parent_id",
            sa.String(36),
            sa.ForeignKey("g1_categories.category_id"),
            nullable=True,
            index=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column(
            "merged_into",
            sa.String(36),
            sa.ForeignKey("g1_categories.category_id"),
            nullable=True,
        ),
        sa.Column("product_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "g1_category_templates",
        sa.Column(
            "category_id",
            sa.String(36),
            sa.ForeignKey("g1_categories.category_id"),
            primary_key=True,
        ),
        sa.Column("field_list", profile_type, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "c7_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("intake_id", sa.String(36), nullable=False, index=True),
        sa.Column("category_id", sa.String(36), nullable=False),
        sa.Column("layer", sa.Integer(), nullable=False),
        sa.Column("field_list", profile_type, nullable=False),
        sa.Column("detail", profile_type, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "g2_field_candidates",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=True, index=True),
        sa.Column("field_name", sa.String(128), nullable=False),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("source_layer", sa.String(32), nullable=False),
        sa.Column("source_route", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("dup", sa.Boolean(), nullable=False),
        sa.Column("related_fid", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("source_layer", "field_name", name="uq_candidate_source_name"),
    )

    # Q2 初始信号权重：文本三信号 0.50/0.33/0.17（Σ=1，图像后置）。
    weights = sa.table(
        "c1_signal_weights",
        sa.column("signal", sa.String),
        sa.column("signal_name", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("weight", sa.Float),
        sa.column("scoring_method", sa.String),
    )
    op.bulk_insert(
        weights,
        [
            {"signal": "name", "signal_name": "产品名", "enabled": True, "weight": 0.50,
             "scoring_method": "text"},
            {"signal": "brief", "signal_name": "简介", "enabled": True, "weight": 0.33,
             "scoring_method": "text"},
            {"signal": "sellpoint", "signal_name": "卖点", "enabled": True, "weight": 0.17,
             "scoring_method": "text"},
        ],
    )

    # Q7 初始行业阈值：medical 0.90 敏感 / electronics 0.80 / general 0.85 默认档。
    industries = sa.table(
        "c1_industry_thresholds",
        sa.column("industry", sa.String),
        sa.column("keywords", profile_type),
        sa.column("threshold", sa.Float),
        sa.column("sensitive", sa.Boolean),
        sa.column("enabled", sa.Boolean),
        sa.column("is_default", sa.Boolean),
    )
    op.bulk_insert(
        industries,
        [
            {"industry": "medical", "keywords": ["医疗器械", "医用"], "threshold": 0.90,
             "sensitive": True, "enabled": True, "is_default": False},
            {"industry": "electronics", "keywords": ["电子", "数码", "电器"],
             "threshold": 0.80, "sensitive": False, "enabled": True, "is_default": False},
            {"industry": "general", "keywords": [], "threshold": 0.85,
             "sensitive": False, "enabled": True, "is_default": True},
        ],
    )


def downgrade() -> None:
    op.drop_table("g2_field_candidates")
    op.drop_table("c7_runs")
    op.drop_table("g1_category_templates")
    op.drop_table("g1_categories")
    op.drop_table("ops_todos")
    op.drop_table("c1_records")
    op.drop_table("c1_industry_thresholds")
    op.drop_table("c1_signal_weights")
