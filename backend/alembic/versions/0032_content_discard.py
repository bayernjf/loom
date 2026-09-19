"""Q124 (Q56-b) P4 slice: content discard-and-return-to-pool.

- add content_products.discard_reason (nullable Text): the "hard-birth reason"
  recorded when operations discards a content skeleton (Q56: after the
  regenerate cap is hit, "transfer to manual OR discard the skeleton back to
  the pool");
- replace the plain unique constraint uq_content_final_language_kind
  (final_id, language, kind) with a partial unique index that excludes
  discarded rows, so a discarded product releases its slot and the same
  final_id/language/kind can be generated again ("back to the pool").

The ORM model declares the index with both postgresql_where and sqlite_where
(create_all under SQLite); the migration itself targets PostgreSQL (same
convention as 0028, whose constraint drop is not batch-wrapped).

Revision ID: 0032_content_discard
Revises: 0031_article_semantic_seed
Create Date: 2026-09-19

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032_content_discard"
down_revision: str | None = "0031_article_semantic_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "content_products",
        sa.Column("discard_reason", sa.Text(), nullable=True),
    )
    op.drop_constraint(
        "uq_content_final_language_kind", "content_products", type_="unique"
    )
    op.create_index(
        "uq_content_final_language_kind",
        "content_products",
        ["final_id", "language", "kind"],
        unique=True,
        postgresql_where=sa.text("status <> 'discarded'"),
    )


def downgrade() -> None:
    # NOTE: restoring the plain unique constraint fails if discarded rows
    # already share a (final_id, language, kind) key; V1 holds no production
    # data, so no reconciliation is performed.
    op.drop_index("uq_content_final_language_kind", table_name="content_products")
    op.create_unique_constraint(
        "uq_content_final_language_kind",
        "content_products",
        ["final_id", "language", "kind"],
    )
    op.drop_column("content_products", "discard_reason")
