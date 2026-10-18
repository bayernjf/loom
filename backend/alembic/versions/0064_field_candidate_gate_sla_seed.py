"""Q368/Q68: seed the field-candidate gate SLA knob as a hot-updatable config item.

Pure seed migration (no schema change). Q68 (docs/25 §3.2, line 164) left
「g2FieldCandidate 挂运营待办未实现」——new G2 field candidates (c7 Layer4 /
wf02_dim_source) now open a dictionary-admin Gate OpsTodo on creation (this
batch). Their due date reads this knob; the default 7 days is an engineering
default (business can retune it hot in the admin config console, same pattern
as Q18's ``atom.evidence_timeout_days``).

ON CONFLICT DO NOTHING preserves any operations-edited row; downgrade deletes
a row only when its full column fingerprint still matches the seed (0057/Q351
rule), so a knob operations has since retuned survives.

Revision ID: 0064_field_candidate_gate_sla_seed
Revises: 0063_pwc_funnel_knobs_seed
Create Date: 2026-10-17

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0064_field_candidate_gate_sla_seed"
down_revision: str | None = "0063_pwc_funnel_knobs_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_KEYS = ("fieldpool.candidate_gate_sla_days",)
# 缺键即硬失败（不静默 no-op）：seeds.py 是唯一事实源，迁移必须与它对账。
_SEEDS = [next(row for row in CONFIG_SEEDS if row[0] == key) for key in _SEED_KEYS]
_SEED_VERSION_NOTE = "Q368 seed"


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
