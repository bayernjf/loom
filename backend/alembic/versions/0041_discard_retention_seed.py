"""Q187 (C4) slice: seed content.discard_retention_days config item.

Pure seed migration (no schema change). Q124 made `discarded` a terminal state
that frees the (final_id, language, kind) unique slot, but never defined how
long such rows are kept (docs/20 §6.5 C4: "归档策略未定义"). This adds the
retention window as a hot-updatable config-center knob; the physical purge job
itself is gated by LOOM_DISCARD_PURGE_ENABLED (default off). Idempotent
ON CONFLICT DO NOTHING (same pattern as 0018/0021/0022).

Revision ID: 0041_discard_retention_seed
Revises: 0040_staff_api_keys
Create Date: 2026-09-24

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0041_discard_retention_seed"
down_revision: str | None = "0040_staff_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_KEY = "content.discard_retention_days"
# 单一键，缺失即 StopIteration 硬失败（不静默 no-op）。
_SEED = next(row for row in CONFIG_SEEDS if row[0] == _SEED_KEY)


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
    key, category, value_type, value, source_ref, validation = _SEED
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
            "version_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-config-seed:{key}")),
            "key": key,
            "version": 1,
            "value": value,
            "change_note": "Q187 seed",
            "changed_by": None,
        }],
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM config_item_versions WHERE key = '{_SEED_KEY}'")
    op.execute(f"DELETE FROM config_items WHERE key = '{_SEED_KEY}'")
