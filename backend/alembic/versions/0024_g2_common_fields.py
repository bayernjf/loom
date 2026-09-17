"""Q115 seed: G2 common fields (product-intake 18-field baseline, 12 of 18).

The source HTML (V6.0 requirement spec, ~27k lines) is permanently lost. Q115
decides the fid values are engineering-authored system identifiers (NOT source-
authoritative), while field_name holds the Chinese canonical names enumerated in
docs/04. Only 12 of the 18 common fields are enumerable from docs/04 — the
remaining 6 are 【原文未给出，待补】 and are intentionally NOT seeded.

Idempotent ON CONFLICT DO NOTHING (same pattern as 0022).

Revision ID: 0024_g2_common_fields
Revises: 0023_tenant_registry
Create Date: 2026-09-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_g2_common_fields"
down_revision: str | None = "0023_tenant_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fid = 工程定稿系统标识符（Q115）；field_name = 中文 canonical（docs/04:58 枚举）。
_G2_COMMON_SEEDS = [
    ("f_name", "产品名"),
    ("f_brand", "品牌"),
    ("f_intro", "简介"),
    ("f_selling_points", "卖点"),
    ("f_seo", "SEO"),
    ("f_main_image", "主图"),
    ("f_packaging_image", "包装图"),
    ("f_target_market", "目标市场"),
    ("f_language", "语言"),
    ("f_channel", "渠道"),
    ("f_audience", "受众"),
    ("f_content_usage", "内容用途"),
]


def upgrade() -> None:
    bind = op.get_bind()
    g2_fields = sa.table(
        "g2_fields",
        sa.column("fid", sa.String),
        sa.column("cat", sa.String),
        sa.column("field_name", sa.String),
        sa.column("status", sa.String),
    )
    rows = [
        {"fid": fid, "cat": "common", "field_name": name, "status": "active"}
        for fid, name in _G2_COMMON_SEEDS
    ]
    bind.execute(
        postgresql.insert(g2_fields).on_conflict_do_nothing(index_elements=["fid"]),
        rows,
    )


def downgrade() -> None:
    fids = ", ".join(f"'{fid}'" for fid, _ in _G2_COMMON_SEEDS)
    op.execute(f"DELETE FROM g2_fields WHERE fid IN ({fids})")
