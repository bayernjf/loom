"""Q335 slice: seed billing display-price config items (D3.11-6).

Pure seed migration (no schema change). docs/09 D3.11-6 lists Basic $999 /
Pro $2999 / Enterprise $9999 as display-only monthly prices; the agency tier
price is 【待业务方回填】 and intentionally not seeded (SEED absence = the
「待补」 display state). Prices are hot-updatable via the config center; any
change writes a config.update audit (Q335 / design-v2-billing-subscription
§3.3). No charging, invoicing, or quota interception is implied.

Idempotent ON CONFLICT DO NOTHING (same pattern as 0021/0022/0041/0049).

Revision ID: 0055_billing_price_seed
Revises: 0054_wf07_skill_scene_seed
Create Date: 2026-10-10

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0055_billing_price_seed"
down_revision: str | None = "0054_wf07_skill_scene_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_KEYS = (
    "billing.price_monthly_usd.basic",
    "billing.price_monthly_usd.pro",
    "billing.price_monthly_usd.enterprise",
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
                "change_note": "Q335 seed",
                "changed_by": None,
            }],
        )


def downgrade() -> None:
    keys = ", ".join(f"'{key}'" for key in _SEED_KEYS)
    op.execute(f"DELETE FROM config_item_versions WHERE key IN ({keys})")
    op.execute(f"DELETE FROM config_items WHERE key IN ({keys})")
