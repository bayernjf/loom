"""Q125 (Q60c) P4 slice: operations publish-info backfill.

Add content_products.published_url / platform_post_id / published_at
(nullable). After customer approval (ready_for_publish), operations
publishes via managed accounts and backfills the platform URL/post ID;
published_at being non-null is the "published" signal. The state machine
gains no published state. Agent scraping and effect-callback ingestion
remain segment-13/P3 (V2).

Revision ID: 0033_content_publish
Revises: 0032_content_discard
Create Date: 2026-09-19

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033_content_publish"
down_revision: str | None = "0032_content_discard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "content_products",
        sa.Column("published_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "content_products",
        sa.Column("platform_post_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "content_products",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_products", "published_at")
    op.drop_column("content_products", "platform_post_id")
    op.drop_column("content_products", "published_url")
