"""P4 (V2) slice 1: content_products table for segment-12 content generation.

Field set is an implementation backfill (docs/04 §3 【待补】) derived from
Q56–Q59 and the segment-12 "read-only FCW consumption" requirement. final_id is
a read-only soft reference (no hard FK, same convention as FCW internal refs).

Revision ID: 0025_content_products
Revises: 0024_g2_common_fields
Create Date: 2026-09-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025_content_products"
down_revision: str | None = "0024_g2_common_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "content_products",
        sa.Column("content_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("product_space_id", sa.String(36), nullable=False),
        sa.Column("final_id", sa.String(36), nullable=False),
        sa.Column("goal", sa.String(32), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("slot_id", sa.String(36), nullable=True),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="article"),
        sa.Column("language", sa.String(16), nullable=False, server_default="zh-CN"),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("review_hits", json_type, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("reject_reason", sa.Text, nullable=True),
        sa.Column("regenerate_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_content_products_tenant", "content_products", ["tenant_id"])
    op.create_index("ix_content_products_ps", "content_products", ["product_space_id"])
    op.create_index("ix_content_products_final", "content_products", ["final_id"])
    op.create_index("ix_content_products_status", "content_products", ["status"])


def downgrade() -> None:
    op.drop_index("ix_content_products_status", table_name="content_products")
    op.drop_index("ix_content_products_final", table_name="content_products")
    op.drop_index("ix_content_products_ps", table_name="content_products")
    op.drop_index("ix_content_products_tenant", table_name="content_products")
    op.drop_table("content_products")
