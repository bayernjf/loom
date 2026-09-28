"""Q230: seed a minimal flat G1 category set so segment 2 has real options.

Pure seed migration (no schema change). Segment 2 CAT-RECOG builds its
``category_options`` from active ``g1_categories`` rows (Q82 同源); migration
0002 only creates the table, so a freshly migrated DB had zero rows and a real
model returning any category id was rejected with HTTP 502 (Q228, docs/20
§14.2/§14.4 ②-b).

The authoritative G1 category directory is **not** in docs (原文未给出), so this
is not a transcription of a source list. Per the Q115 precedent (g2_fields'
authoritative fids were lost with V6.0 HTML and were engineering-定稿 after a
ruling), the six top-level flat categories below are engineering candidates
**approved at the Gate** (docs/02 C1.174). ``name`` is the V1 zh-CN canonical —
the table has no code column and multilingual dictionary names are deferred to
V3 (Q84).

Idempotent ON CONFLICT DO NOTHING (same pattern as 0018/0021/0022/0041); the ids
are deterministic uuid5 so a re-run is stable and the seeded rows are
identifiable.

Revision ID: 0042_g1_category_seed
Revises: 0041_discard_retention_seed
Create Date: 2026-09-28

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0042_g1_category_seed"
down_revision: str | None = "0041_discard_retention_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (slug, zh-CN canonical name) —— Gate 批准的六个顶层平铺类目（docs/02 C1.174）。
# slug 只用于派生稳定 id，不入库（表无 code 列）。
_SEED: tuple[tuple[str, str], ...] = (
    ("beauty_skincare", "美妆护肤"),
    ("food_beverage", "食品饮料"),
    ("mother_baby", "母婴亲子"),
    ("apparel_bags", "服饰鞋包"),
    ("home_daily", "家居日用"),
    ("health_wellness", "健康保健"),
)

_ID_NAMESPACE = "loom-g1-category-seed"


def category_id(slug: str) -> str:
    """Deterministic id so re-runs are stable and the seed is identifiable."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_ID_NAMESPACE}:{slug}"))


def seed_rows() -> list[dict]:
    """The exact rows this migration inserts (exposed for the contract test)."""
    return [
        {
            "category_id": category_id(slug),
            "parent_id": None,
            "name": name,
            "status": "active",
            "merged_into": None,
            "product_count": 0,
        }
        for slug, name in _SEED
    ]


def upgrade() -> None:
    g1_categories = sa.table(
        "g1_categories",
        sa.column("category_id", sa.String),
        sa.column("parent_id", sa.String),
        sa.column("name", sa.String),
        sa.column("status", sa.String),
        sa.column("merged_into", sa.String),
        sa.column("product_count", sa.Integer),
    )
    op.get_bind().execute(
        postgresql.insert(g1_categories).on_conflict_do_nothing(),
        seed_rows(),
    )


def downgrade() -> None:
    ids = ", ".join(f"'{row['category_id']}'" for row in seed_rows())
    op.execute(f"DELETE FROM g1_categories WHERE category_id IN ({ids})")