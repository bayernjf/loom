"""Q93 M12 unified review workbench: review.batch_pass_confidence seed.

Pure seed migration (no schema change). 0010 seeds the CONFIG_SEEDS snapshot,
so a fresh upgrade already contains the key; idempotent ON CONFLICT DO NOTHING
covers existing databases upgrading from 0020 (same pattern as 0018).

Revision ID: 0021_review_batch_pass_confidence
Revises: 0020_restock_retry_state
Create Date: 2026-09-15

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0021_review_batch_pass_confidence"
down_revision: str | None = "0020_restock_retry_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED = next(row for row in CONFIG_SEEDS if row[0] == "review.batch_pass_confidence")


def upgrade() -> None:
    bind = op.get_bind()
    key, category, value_type, value, source_ref, validation = _SEED
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    config_items_t = sa.table(
        "config_items",
        sa.column("key", sa.String),
        sa.column("category", sa.String),
        sa.column("value", json_type),
        sa.column("value_type", sa.String),
        sa.column("validation", json_type),
        sa.column("source_ref", sa.String),
        sa.column("version", sa.Integer),
    )
    config_versions_t = sa.table(
        "config_item_versions",
        sa.column("version_id", sa.String),
        sa.column("key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("value", json_type),
        sa.column("change_note", sa.String),
        sa.column("changed_by", sa.String),
    )
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-config-seed:{key}"))
    bind.execute(
        postgresql.insert(config_items_t).on_conflict_do_nothing(),
        [{
            "key": key,
            "category": category,
            "value": value,
            "value_type": value_type,
            "validation": validation,
            "source_ref": source_ref,
            "version": 1,
        }],
    )
    bind.execute(
        postgresql.insert(config_versions_t).on_conflict_do_nothing(),
        [{
            "version_id": version_id,
            "key": key,
            "version": 1,
            "value": value,
            "change_note": "Q93 seed",
            "changed_by": None,
        }],
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM config_item_versions WHERE key = 'review.batch_pass_confidence'"
    )
    op.execute("DELETE FROM config_items WHERE key = 'review.batch_pass_confidence'")
