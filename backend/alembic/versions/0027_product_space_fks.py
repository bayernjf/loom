"""Q118: add real DB-level foreign keys on product_spaces.category_node_id
(-> g1_categories.category_id) and product_spaces.active_pws_id
(-> pws_snapshots.pws_id). Both columns were created as bare String(36) soft
references in migration 0001 and have no writers in V1 code, so they only
contain NULLs today; the orphan-nullification below is defensive for any
manually seeded environment.

Revision ID: 0027_product_space_fks
Revises: 0026_article_gen_seed
Create Date: 2026-09-18

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027_product_space_fks"
down_revision: str | None = "0026_article_gen_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_CATEGORY = "fk_product_spaces_category_node_id"
FK_ACTIVE_PWS = "fk_product_spaces_active_pws_id"


def upgrade() -> None:
    # Defensive: detach orphan soft references before enforcing the constraint.
    op.execute(
        """
        UPDATE product_spaces SET category_node_id = NULL
        WHERE category_node_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM g1_categories
              WHERE g1_categories.category_id = product_spaces.category_node_id
          )
        """
    )
    op.execute(
        """
        UPDATE product_spaces SET active_pws_id = NULL
        WHERE active_pws_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM pws_snapshots
              WHERE pws_snapshots.pws_id = product_spaces.active_pws_id
          )
        """
    )
    op.create_foreign_key(
        FK_CATEGORY,
        "product_spaces",
        "g1_categories",
        ["category_node_id"],
        ["category_id"],
    )
    op.create_foreign_key(
        FK_ACTIVE_PWS,
        "product_spaces",
        "pws_snapshots",
        ["active_pws_id"],
        ["pws_id"],
    )


def downgrade() -> None:
    op.drop_constraint(FK_ACTIVE_PWS, "product_spaces", type_="foreignkey")
    op.drop_constraint(FK_CATEGORY, "product_spaces", type_="foreignkey")
