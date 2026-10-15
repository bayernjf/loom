"""Q361: seed the CP-BAN base-layer default wordlist (6 words).

Pure seed migration (no schema change). docs/25 §8.1 #15 tracked
「CP-BAN 默认 6 词未种子」-- the ``compliance_wordlist`` table (Q48, created
in 0004) shipped empty while PRD line 126 fixed the base-layer CP-BAN
disable words: permanent removal / cure / treat / 根治 / 保证有效 / 100%.
All six are ``critical`` level with ``action=ban`` on ``layer=base``
(Q50: base defaults are not configurable via the admin UI, but the rows
still exist so segment-4/5/10 scans actually hit something).

ON CONFLICT DO NOTHING keeps the seed idempotent on re-upgrade; downgrade
deletes a row only when its full column fingerprint still matches the seed
(same rule as 0057/Q351), so a row operations has since retuned survives.

Revision ID: 0061_compliance_wordlist_seed
Revises: 0060_inspiration_entries
Create Date: 2026-10-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0061_compliance_wordlist_seed"
down_revision: str | None = "0060_inspiration_entries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# PRD line 126（docs/01 §3 段10）CP-BAN 禁用维度 6 词，底座默认层。
_SEED_WORDS = (
    "permanent removal",
    "cure",
    "treat",
    "根治",
    "保证有效",
    "100%",
)


def _wordlist_table():
    return sa.table(
        "compliance_wordlist",
        sa.column("entry_id", sa.String),
        sa.column("word", sa.String),
        sa.column("level", sa.String),
        sa.column("action", sa.String),
        sa.column("layer", sa.String),
        sa.column("status", sa.String),
    )


def upgrade() -> None:
    import uuid

    bind = op.get_bind()
    wordlist = _wordlist_table()
    bind.execute(
        postgresql.insert(wordlist).on_conflict_do_nothing(),
        [
            {
                # 主键默认值在应用层（models._uuid_pk），迁移必须显式给 entry_id；
                # uuid5 确定性 ⇒ 任何环境重播同一行、downgrade 可精确对账。
                "entry_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-wordlist:{word}")),
                "word": word,
                "level": "critical",
                "action": "ban",
                "layer": "base",
                "status": "active",
            }
            for word in _SEED_WORDS
        ],
    )


def downgrade() -> None:
    """Remove a seed row only while its full fingerprint is still pristine."""
    bind = op.get_bind()
    wordlist = _wordlist_table()
    for word in _SEED_WORDS:
        stored = bind.execute(
            sa.select(
                wordlist.c.level,
                wordlist.c.action,
                wordlist.c.layer,
                wordlist.c.status,
            ).where(wordlist.c.word == word)
        ).first()
        if stored is None:
            continue
        if tuple(stored) != ("critical", "ban", "base", "active"):
            continue  # 运营改过该词条 ⇒ 保留
        bind.execute(sa.delete(wordlist).where(wordlist.c.word == word))
