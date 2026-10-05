"""Q288 (awaiting-ruling item 7, option C): DB-level guard, one active package per triple.

The service's select-then-insert (app/decision/layer_strategy/service.py:113-124 ->
PackageExists -> 409) is not concurrency-safe; the audit (docs/23 §8.3 + Q278 errata)
found migration 0008 created `packages` with five plain indexes and NO uniqueness, so
concurrent double-creates of the same active triple were unguarded. The owner ruled to
add the partial unique index (design-p2 §6 review material, Q284; ruled 2026-10-05
"按你建议来" — option C, zero rows in the wild, no archive pass needed).

The key matches the service check verbatim: (product_space_id, platform, goal, kind)
WHERE status = 'active'. tenant_id is deliberately NOT part of the key: a product
space already fixes the tenant, and adding it would widen the semantics.

The index name deliberately does NOT reuse the phantom `uq_package_active_triple`
cited as an existing fact by five documents since Q272 — it never existed (Q278
errata); reusing it would let "the docs always said so" keep hiding "the code never
had it".

The model twin lives in app/decision/layer_strategy/models.py __table_args__
(postgresql_where + sqlite_where double declaration) — Q207's ORM⇄DB drift gate
fails if the migration and the model disagree.

Revision ID: 0048_packages_active_triple_unique
Revises: 0047_layer_spaces
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0048_packages_active_triple_unique"
down_revision: str | None = "0047_layer_spaces"


def upgrade() -> None:
    op.create_index(
        "uq_packages_active_triple",
        "packages",
        ["product_space_id", "platform", "goal", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_packages_active_triple", table_name="packages")
