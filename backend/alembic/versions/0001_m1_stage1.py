"""M1 stage-1 core tables: intakes, product spaces, g2 fields, audit logs

Revision ID: 0001_m1_stage1
Revises:
Create Date: 2026-09-13 18:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_m1_stage1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# JSONB on PostgreSQL, JSON elsewhere (tests), per app/core/db.JSONType.
profile_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "g2_fields",
        sa.Column("fid", sa.String(64), primary_key=True),
        sa.Column("cat", sa.String(32), nullable=False),
        sa.Column("field_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    )
    op.create_index("ix_g2_fields_cat", "g2_fields", ["cat"])

    op.create_table(
        "product_intake_applications",
        sa.Column("intake_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("profile", profile_type, nullable=False),
        sa.Column("category_pending_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_intakes_tenant", "product_intake_applications", ["tenant_id"])
    op.create_index("ix_intakes_status", "product_intake_applications", ["status"])

    op.create_table(
        "product_spaces",
        sa.Column("product_space_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "intake_id",
            sa.String(36),
            sa.ForeignKey("product_intake_applications.intake_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("category_node_id", sa.String(36), nullable=True),
        sa.Column("industry_tag", sa.String(64), nullable=True),
        sa.Column("sensitive_industry", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("lifecycle", sa.String(16), nullable=False, server_default="modeling"),
        sa.Column("active_pws_id", sa.String(36), nullable=True),
        sa.Column("business_owner", sa.String(64), nullable=True),
        sa.Column("profile_snapshot", profile_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_spaces_tenant", "product_spaces", ["tenant_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=True),
        sa.Column("actor_roles", profile_type, nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("detail", profile_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_tenant", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_entity", "audit_logs", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_entity", table_name="audit_logs")
    op.drop_index("ix_audit_tenant", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_spaces_tenant", table_name="product_spaces")
    op.drop_table("product_spaces")
    op.drop_index("ix_intakes_status", table_name="product_intake_applications")
    op.drop_index("ix_intakes_tenant", table_name="product_intake_applications")
    op.drop_table("product_intake_applications")
    op.drop_index("ix_g2_fields_cat", table_name="g2_fields")
    op.drop_table("g2_fields")
