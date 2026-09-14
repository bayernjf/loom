"""M8 stage-11 FCW assembly: final content whitelists + assembly tasks (Q52-Q55)

Revision ID: 0009_m8_stage11
Revises: 0008_m11_stage78
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_m8_stage11"
down_revision: str | None = "0008_m11_stage78"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "final_content_whitelists",
        sa.Column("final_id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), nullable=True, index=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("product_space_id", sa.String(36), nullable=False, index=True),
        sa.Column("pws_id", sa.String(36), nullable=False, index=True),
        sa.Column("pwc_id", sa.String(36), nullable=False),
        sa.Column("pcp_id", sa.String(36), nullable=False),
        sa.Column("csp_package_id", sa.String(36), nullable=False),
        sa.Column("cstp_package_id", sa.String(36), nullable=False),
        sa.Column("cep_package_id", sa.String(36), nullable=False),
        sa.Column("ccr_report_id", sa.String(36), nullable=True),
        sa.Column("law_review_id", sa.String(36), nullable=True),
        sa.Column("platform", sa.String(32), nullable=False, index=True),
        sa.Column("slot_id", sa.String(36), nullable=False, index=True),
        sa.Column("goal", sa.String(32), nullable=False, index=True),
        sa.Column("country", sa.String(8), nullable=True, index=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("score_detail", json_type, nullable=False),
        sa.Column("score_incomplete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("guards", json_type, nullable=False),
        sa.Column("guards_passed", sa.Boolean(), nullable=False),
        sa.Column(
            "publish_status",
            sa.String(16),
            nullable=False,
            server_default="published",
            index=True,
        ),
        sa.Column("issued_by", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "pws_id", "pwc_id", "platform", "slot_id", name="uq_fcw_same_issue"
        ),
    )

    op.create_table(
        "fcw_assembly_tasks",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("product_space_id", sa.String(36), nullable=False, index=True),
        sa.Column("pws_id", sa.String(36), nullable=False, index=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("goal", sa.String(32), nullable=False),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("slot_ids", json_type, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("results", json_type, nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("fcw_assembly_tasks")
    op.drop_table("final_content_whitelists")
