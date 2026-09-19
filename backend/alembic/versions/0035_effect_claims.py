"""Q127 segment-13 orphan effect manual claim: effect_claims mapping + audit cols.

Second inbound slice of the segment-13 feedback loop (Q60a, contract in
docs/05 §1.1.1 / docs/11 §2.1). Operations manually binds an orphaned
external_content_id (the push-side id that matched no live content) to a real
content_products row. The mapping is persistent: later pushes for the same
external_content_id — both idempotent overwrites and new captured_at points —
match via the claim and never fall back to orphan.

- New table effect_claims: one manual mapping per external_content_id.
- effect_records gains claimed_by / claimed_at for row-level provenance;
  claimed rows carry matched_content_id like automatic matches.

Revision ID: 0035_effect_claims
Revises: 0034_effect_records
Create Date: 2026-09-19

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035_effect_claims"
down_revision: str | None = "0034_effect_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "effect_claims",
        sa.Column("external_content_id", sa.String(36), primary_key=True),
        sa.Column("content_id", sa.String(36), nullable=False),
        sa.Column("claimed_by", sa.String(64), nullable=False),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["content_products.content_id"],
            name="fk_effect_claims_content",
        ),
    )
    op.add_column(
        "effect_records", sa.Column("claimed_by", sa.String(64), nullable=True)
    )
    op.add_column(
        "effect_records",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("effect_records", "claimed_at")
    op.drop_column("effect_records", "claimed_by")
    op.drop_table("effect_claims")
