"""Q350 (docs/19 list-2 #13 甲): seed sensitive industries food/maternal-infant.

Pure seed migration (no schema change). Q7 already seeded medical as
sensitive (0002); Q11/Q14/Q49 derive from ProductSpace.sensitive_industry,
whose source of truth is this table's `sensitive` flag. The Q347 audit found
the "sensitive industry dictionary" incomplete: 食品/母婴/医疗器械 only had
the medical-device row. This migration adds the two missing sensitive rows.

Threshold values have no authoritative source in docs; per the "no invented
red lines" rule they take the default-tier value 0.85 rather than a guessed
stricter number. Operations can adjust via the Q7 CRUD afterwards (every
change is audited). ON CONFLICT DO NOTHING preserves any operations-edited
or pre-existing row (same pattern as 0021/0049); downgrade deletes a row only
when its full column fingerprint still matches the seed (industry + keywords
JSONB + threshold 0.85 + sensitive/enabled flags + is_default=false), so a
row operations has since customized via Q7 CRUD is left untouched.

Revision ID: 0057_q7_sensitive_industry_seeds
Revises: 0056_video_segments_objects
Create Date: 2026-10-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0057_q7_sensitive_industry_seeds"
down_revision: str | None = "0056_video_segments_objects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# industry -> 种子 keywords（downgrade 指纹的一部分，逐字对应 upgrade 的插入行）。
_SEED_KEYWORDS = {
    "food": ["食品"],
    "maternal_infant": ["母婴"],
}


def _industries_table():
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    return sa.table(
        "c1_industry_thresholds",
        sa.column("industry", sa.String),
        sa.column("keywords", json_type),
        sa.column("threshold", sa.Float),
        sa.column("sensitive", sa.Boolean),
        sa.column("enabled", sa.Boolean),
        sa.column("is_default", sa.Boolean),
    )


def upgrade() -> None:
    bind = op.get_bind()
    industries = _industries_table()
    bind.execute(
        postgresql.insert(industries).on_conflict_do_nothing(),
        [
            {"industry": name, "keywords": keywords, "threshold": 0.85,
             "sensitive": True, "enabled": True, "is_default": False}
            for name, keywords in _SEED_KEYWORDS.items()
        ],
    )


def downgrade() -> None:
    # 只删「整行指纹仍与种子一致」的行：运营经 Q7 CRUD 改过 threshold/keywords/
    # 开关位的定制行必须保留（升/降级对称，不误删运营数据）。
    bind = op.get_bind()
    industries = _industries_table()
    for name, keywords in _SEED_KEYWORDS.items():
        bind.execute(
            industries.delete()
            .where(industries.c.industry == name)
            .where(industries.c.keywords == keywords)
            .where(industries.c.threshold == 0.85)
            .where(industries.c.sensitive.is_(True))
            .where(industries.c.enabled.is_(True))
            .where(industries.c.is_default.is_(False))
        )
