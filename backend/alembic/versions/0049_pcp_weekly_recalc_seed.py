"""Q294 slice: seed the PCP weekly-recalc reminder cadence config items.

Pure seed migration (no schema change). docs/01 段8 PT-PCP-V1.5 requires
「动态信号每周更新触发重算」, but the original text only says "weekly" — the
weekday/hour/timezone are 【原文未给出，待补】. This registers the cadence as
hot-updatable config-center knobs (engineering 甲 defaults: Monday 02:00,
UTC+8 = Asia/Shanghai) so the business side can change the rhythm without a
deploy. The scan job itself is gated by LOOM_PCP_WEEKLY_SCAN_ENABLED (default
off) and only opens OpsTodo reminders — it never writes weights back.

Idempotent ON CONFLICT DO NOTHING (same pattern as 0018/0021/0022/0041).

Revision ID: 0049_pcp_weekly_recalc_seed
Revises: 0048_packages_active_triple_unique
Create Date: 2026-10-06

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0049_pcp_weekly_recalc_seed"
down_revision: str | None = "0048_packages_active_triple_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_KEYS = (
    "platform.recalc_weekday",
    "platform.recalc_hour",
    "platform.recalc_tz_offset_hours",
    "platform.recalc_todo_due_days",
)
# 缺键即硬失败（不静默 no-op）：seeds.py 是唯一事实源，迁移必须与它对账。
_SEEDS = [next(row for row in CONFIG_SEEDS if row[0] == key) for key in _SEED_KEYS]


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
    for key, category, value_type, value, source_ref, validation in _SEEDS:
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
                "change_note": "Q294 seed",
                "changed_by": None,
            }],
        )


def downgrade() -> None:
    keys = ", ".join(f"'{key}'" for key in _SEED_KEYS)
    op.execute(f"DELETE FROM config_item_versions WHERE key IN ({keys})")
    op.execute(f"DELETE FROM config_items WHERE key IN ({keys})")
