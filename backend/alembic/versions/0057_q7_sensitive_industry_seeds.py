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
or pre-existing row (same pattern as 0021/0049); downgrade removes exactly
these two seed industries.

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

_SEED_INDUSTRIES = ("food", "maternal_infant")


def upgrade() -> None:
    bind = op.get_bind()
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    industries = sa.table(
        "c1_industry_thresholds",
        sa.column("industry", sa.String),
        sa.column("keywords", json_type),
        sa.column("threshold", sa.Float),
        sa.column("sensitive", sa.Boolean),
        sa.column("enabled", sa.Boolean),
        sa.column("is_default", sa.Boolean),
    )
    bind.execute(
        postgresql.insert(industries).on_conflict_do_nothing(),
        [
            {"industry": "food", "keywords": ["食品"], "threshold": 0.85,
             "sensitive": True, "enabled": True, "is_default": False},
            {"industry": "maternal_infant", "keywords": ["母婴"], "threshold": 0.85,
             "sensitive": True, "enabled": True, "is_default": False},
        ],
    )


def downgrade() -> None:
    names = ", ".join(f"'{name}'" for name in _SEED_INDUSTRIES)
    op.execute(
        f"DELETE FROM c1_industry_thresholds WHERE industry IN ({names})"
    )
