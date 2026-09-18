"""Q120 (Q57) P4 slice: add content_products AI quality-score columns.

quality_score/quality_issues are populated by the ARTICLE-QC model scene
(see 0030). Per Q57 the score is advisory only and never blocks publish or
drives an automatic rejection, so both columns are nullable.

Revision ID: 0029_content_quality
Revises: 0028_content_languages
Create Date: 2026-09-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029_content_quality"
down_revision: str | None = "0028_content_languages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column(
        "content_products", sa.Column("quality_score", sa.Float(), nullable=True)
    )
    op.add_column(
        "content_products", sa.Column("quality_issues", json_type, nullable=True)
    )


def downgrade() -> None:
    op.drop_column("content_products", "quality_issues")
    op.drop_column("content_products", "quality_score")
