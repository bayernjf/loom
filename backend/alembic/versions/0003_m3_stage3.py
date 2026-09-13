"""M3 stage-3 field pool planning: source routes, field pools, pool dimensions

Revision ID: 0003_m3_stage3
Revises: 0002_m2_stage2
Create Date: 2026-09-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_m3_stage3"
down_revision: str | None = "0002_m2_stage2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

profile_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "fp_source_routes",
        sa.Column("route", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "field_pools",
        sa.Column("pool_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "product_space_id",
            sa.String(36),
            sa.ForeignKey("product_spaces.product_space_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("gate", sa.String(16), nullable=False, index=True),
        sa.Column("compliant", sa.Boolean(), nullable=False),
        sa.Column("violations", profile_type, nullable=False),
        sa.Column("target_atom_min", sa.Integer(), nullable=False),
        sa.Column("target_atom_max", sa.Integer(), nullable=False),
        sa.Column("submitted_by", sa.String(64), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("product_space_id", name="uq_field_pool_product_space"),
    )
    op.create_table(
        "fp_dimensions",
        sa.Column("dimension_id", sa.String(36), primary_key=True),
        sa.Column(
            "pool_id",
            sa.String(36),
            sa.ForeignKey("field_pools.pool_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("role", sa.String(32), nullable=False, index=True),
        sa.Column("source_route", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("field_name", sa.String(128), nullable=False),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("fid", sa.String(64), nullable=True, index=True),
        sa.Column("candidate_id", sa.String(36), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("needs_detail", sa.Boolean(), nullable=False),
        sa.Column("dup", sa.Boolean(), nullable=False),
        sa.Column("related_fid", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )

    # Q8 默认 6 路（运营上线后可增删改；不足原文 7 路无妨，Q8 已裁）。
    op.bulk_insert(
        sa.table(
            "fp_source_routes",
            sa.column("route", sa.String),
            sa.column("name", sa.String),
            sa.column("enabled", sa.Boolean),
            sa.column("sort_order", sa.Integer),
        ),
        [
            {"route": "user_input", "name": "用户输入/产品资料", "enabled": True, "sort_order": 1},
            {"route": "common_inspiration", "name": "通用灵感库", "enabled": True, "sort_order": 2},
            {"route": "product_inspiration", "name": "产品专属灵感库", "enabled": True, "sort_order": 3},
            {"route": "category_template", "name": "类目模板 G1", "enabled": True, "sort_order": 4},
            {"route": "g2_frequent", "name": "G2 高频字段", "enabled": True, "sort_order": 5},
            {"route": "compliance_risk", "name": "合规风险面/维度生成规则", "enabled": True, "sort_order": 6},
        ],
    )


def downgrade() -> None:
    op.drop_table("fp_dimensions")
    op.drop_table("field_pools")
    op.drop_table("fp_source_routes")
