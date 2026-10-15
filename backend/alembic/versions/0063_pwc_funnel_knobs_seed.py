"""Q362: seed the Q21 funnel pluggability knobs as hot-updatable config items.

Pure seed migration (no schema change). Q21 (docs/02 C1.4) makes the whole
PWC funnel operations-configurable: prefilter rule switches and detector
switches/order. docs/25 §3.4 tracked「检测项开关/顺序未配置化」as a gap.

Two json knobs are seeded here:

- ``pwc.detectors`` — the pluggable detector list (compliance_wordlist is
  implemented and enabled by default; logic_ai/fit_ai ship with M10 and stay
  disabled). Enabling an unimplemented detector is rejected honestly by the
  service instead of being silently skipped.
- ``pwc.prefilter_rules`` — the three cheap prefilter rules named in the Q21
  ruling (dimension_mutex / market_filter / customer_exclusion). Their data
  sources are【原文未给出，待补】, so only the switch skeleton is seeded,
  all disabled; enabling any rule is rejected honestly by the service.

json keys are passed through wholesale by the config center (no deep
coerce-validation); name legitimacy is defended consumer-side in
``pwc_rules.detectors()/prefilter_rules()`` (same pattern as Q361's
``pws.refreeze_tier_map``).

ON CONFLICT DO NOTHING preserves any operations-edited row; downgrade
deletes a row only when its full column fingerprint still matches the seed
(0057/Q351 rule), so a knob operations has since retuned survives.

Revision ID: 0063_pwc_funnel_knobs_seed
Revises: 0062_pws_refreeze_tiers_seed
Create Date: 2026-10-15

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0063_pwc_funnel_knobs_seed"
down_revision: str | None = "0062_pws_refreeze_tiers_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_KEYS = ("pwc.detectors", "pwc.prefilter_rules")
# 缺键即硬失败（不静默 no-op）：seeds.py 是唯一事实源，迁移必须与它对账。
_SEEDS = [next(row for row in CONFIG_SEEDS if row[0] == key) for key in _SEED_KEYS]
_SEED_VERSION_NOTE = "Q362 seed"


def _config_items_table():
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    return sa.table(
        "config_items",
        sa.column("key", sa.String),
        sa.column("category", sa.String),
        sa.column("value", json_type),
        sa.column("value_type", sa.String),
        sa.column("validation", json_type),
        sa.column("source_ref", sa.String),
        sa.column("version", sa.Integer),
    )


def _config_versions_table():
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    return sa.table(
        "config_item_versions",
        sa.column("version_id", sa.String),
        sa.column("key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("value", json_type),
        sa.column("change_note", sa.String),
        sa.column("changed_by", sa.String),
    )


def upgrade() -> None:
    bind = op.get_bind()
    config_items = _config_items_table()
    config_versions = _config_versions_table()
    for key, category, value_type, value, source_ref, validation in _SEEDS:
        bind.execute(
            postgresql.insert(config_items).on_conflict_do_nothing(),
            [
                {
                    "key": key,
                    "category": category,
                    "value": value,
                    "value_type": value_type,
                    "validation": validation,
                    "source_ref": source_ref,
                    "version": 1,
                }
            ],
        )
        bind.execute(
            postgresql.insert(config_versions).on_conflict_do_nothing(),
            [
                {
                    "version_id": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"loom-config-seed:{key}")
                    ),
                    "key": key,
                    "version": 1,
                    "value": value,
                    "change_note": _SEED_VERSION_NOTE,
                    "changed_by": None,
                }
            ],
        )


def downgrade() -> None:
    """Remove each seed row only while it is still pristine.

    Same double fingerprint as 0058/0062: a ``config_items`` row is deleted
    only when both JSON payloads still match its seed (compared in Python
    before the DELETE -- ``jsonb = integer`` has no operator). The
    version-history delete is additionally pinned to this migration's own
    ``change_note`` so another migration's audit trail is never erased.
    """
    bind = op.get_bind()
    config_items = _config_items_table()
    config_versions = _config_versions_table()

    for key, _category, _value_type, value, _source_ref, validation in _SEEDS:
        stored = bind.execute(
            sa.select(config_items.c.value, config_items.c.validation).where(
                config_items.c.key == key
            )
        ).first()
        if stored is None:
            continue  # 键不在（已被删或从未播）——无事可做
        if stored[0] != value or stored[1] != validation:
            continue  # 运营改过 value/validation ⇒ 整行连同版本历史一并保留

        bind.execute(
            config_versions.delete()
            .where(config_versions.c.key == key)
            .where(config_versions.c.version == 1)
            .where(config_versions.c.change_note == _SEED_VERSION_NOTE)
        )
        bind.execute(sa.delete(config_items).where(config_items.c.key == key))
