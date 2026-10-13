"""Q352: seed the fit_score self-learning observation window knob.

Pure seed migration (no schema change). ``fit_learning.py`` (Q325) computes the
advisory candidate scores, but until Q352 nothing consumed it. The wiring now
reads two things: the process gate ``LOOM_FIT_LEARNING_ENABLED`` (default off)
and this knob -- how many days of ``effect_records`` a slot's suggestion looks
back over.

Q293 listed 「观察窗与回溯口径」 (the observation window and lookback rule) as one
of four business rules the real self-learning path still awaits (docs/02 C1.236),
so the number has no authoritative source. Following
the Q294 precedent the engineering default is registered as a hot-updatable
config-center knob labelled 原文未给出 (90 days, same order of magnitude as
Q61's ``hot.window_days``) instead of being frozen into code -- operations can
change it without a deploy, and every change is audited by the config center.

ON CONFLICT DO NOTHING preserves any operations-edited row (same pattern as
0021/0049/0057); downgrade deletes a row only when its full column fingerprint
still matches the seed, so a knob operations has since retuned survives.

Revision ID: 0058_fit_learning_window_seed
Revises: 0057_q7_sensitive_industry_seeds
Create Date: 2026-10-13

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0058_fit_learning_window_seed"
down_revision: str | None = "0057_q7_sensitive_industry_seeds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_KEY = "platform.fit_learning_window_days"
# 缺键即硬失败（不静默 no-op）：seeds.py 是唯一事实源，迁移必须与它对账。
_SEED = next(row for row in CONFIG_SEEDS if row[0] == _SEED_KEY)
_SEED_VERSION_NOTE = "Q352 seed"


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
    key, category, value_type, value, source_ref, validation = _SEED
    config_items = _config_items_table()
    config_versions = _config_versions_table()
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
                "version_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-config-seed:{key}")),
                "key": key,
                "version": 1,
                "value": value,
                "change_note": _SEED_VERSION_NOTE,
                "changed_by": None,
            }
        ],
    )


def downgrade() -> None:
    """Remove the seed row only while it is still pristine.

    Two fingerprints matter here. The ``config_items`` row is deleted only when
    both JSON payloads still match the seed (the 0057/Q351 rule: a knob
    operations has retuned must survive an upgrade/downgrade replay). Those two
    columns are compared in Python before the DELETE rather than inside it --
    ``jsonb = integer`` has no operator, and str()-ing a dict into a CAST param
    is not JSON. Probing the single PK row first is the honest form.
    The version-history delete is additionally pinned to this migration's own
    ``change_note``: on a fresh database the v1 history row belongs to 0010
    (change_note "C2 seed", which seeds the live CONFIG_SEEDS snapshot), and
    deleting another migration's audit trail would erase a rollback target
    nobody here created.
    """
    bind = op.get_bind()
    key, _category, _value_type, value, _source_ref, validation = _SEED
    config_items = _config_items_table()
    config_versions = _config_versions_table()

    stored = bind.execute(
        sa.select(config_items.c.value, config_items.c.validation).where(
            config_items.c.key == key
        )
    ).first()
    if stored is None:
        return  # 键不在（已被删或从未播）——无事可做
    if stored[0] != value or stored[1] != validation:
        return  # 运营改过 value/validation ⇒ 整行连同版本历史一并保留

    bind.execute(
        config_versions.delete()
        .where(config_versions.c.key == key)
        .where(config_versions.c.version == 1)
        .where(config_versions.c.change_note == _SEED_VERSION_NOTE)
    )
    bind.execute(sa.delete(config_items).where(config_items.c.key == key))


