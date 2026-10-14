"""Q358: 段3 灵感库本体（product-inspiration，MVP 模块，产品基准段3 法定拆维度来源）。

建 `inspiration_entries`：运营可配置的拆维度依据内容，两层——common（租户内通用，
product_space_id 为 NULL，该租户所有产品共享）／product（绑定单个 product_space_id，
仅该产品专属）。DIM-SOURCE 七路中 common_inspiration / product_inspiration 两路自迁移
0003 起只有路由名、没有数据本体，本表补齐本体，使 AI 拆维度时能取到真实内容。

纯建表、零种子（禁止臆造：内容由运营/客户真实填充，不落任何假数据）。无配置键、
无 partial index，downgrade 直接丢表。

Revision ID: 0060_inspiration_entries
Revises: 0059_video_generation_tasks
Create Date: 2026-10-14

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0060_inspiration_entries"
down_revision: str | None = "0059_video_generation_tasks"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "inspiration_entries",
        sa.Column("entry_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("layer", sa.String(16), nullable=False),
        sa.Column("product_space_id", sa.String(36), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_inspiration_entries_tenant_id", "inspiration_entries", ["tenant_id"]
    )
    op.create_index(
        "ix_inspiration_entries_layer", "inspiration_entries", ["layer"]
    )
    op.create_index(
        "ix_inspiration_entries_product_space_id",
        "inspiration_entries",
        ["product_space_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inspiration_entries_product_space_id", table_name="inspiration_entries"
    )
    op.drop_index("ix_inspiration_entries_layer", table_name="inspiration_entries")
    op.drop_index("ix_inspiration_entries_tenant_id", table_name="inspiration_entries")
    op.drop_table("inspiration_entries")
