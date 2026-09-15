"""Q94 M12 third slice: per-target review SLA hour seeds.

Pure seed migration (no schema change). Five keys for Q70② "each review type
hooks the Q49 SLA engine with its own configured hours"; the source text gives
no concrete hours, so every seed defaults to 72h marked 待补. Idempotent
ON CONFLICT DO NOTHING (same pattern as 0018/0021).

Revision ID: 0022_review_sla_hours
Revises: 0021_review_batch_pass_confidence
Create Date: 2026-09-15

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0022_review_sla_hours"
down_revision: str | None = "0021_review_batch_pass_confidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREFIX = "review.sla_hours."
_SEEDS = [row for row in CONFIG_SEEDS if row[0].startswith(_PREFIX)]


def upgrade() -> None:
    bind = op.get_bind()
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
    item_rows = []
    version_rows = []
    for key, category, value_type, value, source_ref, validation in _SEEDS:
        item_rows.append({
            "key": key,
            "category": category,
            "value": value,
            "value_type": value_type,
            "validation": validation,
            "source_ref": source_ref,
            "version": 1,
        })
        version_rows.append({
            "version_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-config-seed:{key}")),
            "key": key,
            "version": 1,
            "value": value,
            "change_note": "Q94 seed",
            "changed_by": None,
        })
    bind.execute(postgresql.insert(config_items_t).on_conflict_do_nothing(), item_rows)
    bind.execute(postgresql.insert(config_versions_t).on_conflict_do_nothing(), version_rows)


def downgrade() -> None:
    keys = ", ".join(f"'{row[0]}'" for row in _SEEDS)
    op.execute(f"DELETE FROM config_item_versions WHERE key IN ({keys})")
    op.execute(f"DELETE FROM config_items WHERE key IN ({keys})")
