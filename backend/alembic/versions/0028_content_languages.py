"""P4 (V2) Q119 slice: segment-12 multi-language (Q58).

- content_languages catalog (configurable language list, Q58) seeded with zh-CN
  (markets=[] => covers every market, preserving single-language behavior);
- product_spaces.target_languages (nullable JSON; product-side target languages,
  NULL/empty = undeclared => no product-side narrowing of the Q58 intersection);
- content_products unique (final_id, language, kind): each language version is an
  independent product (independent review check / library / customer review, Q58).

Revision ID: 0028_content_languages
Revises: 0027_product_space_fks
Create Date: 2026-09-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.content.models import DEFAULT_LANGUAGE

revision: str = "0028_content_languages"
down_revision: str | None = "0027_product_space_fks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "content_languages",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("markets", json_type, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    languages = sa.table(
        "content_languages",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("markets", json_type),
        sa.column("status", sa.String),
        sa.column("updated_by", sa.String),
    )
    # zh-CN 覆盖全部市场（markets 空），与 Q116 单语言默认行为完全一致。
    op.bulk_insert(
        languages,
        [
            {
                "code": DEFAULT_LANGUAGE,
                "name": "简体中文",
                "markets": [],
                "status": "active",
                "updated_by": "_migration_seed",
            }
        ],
    )

    op.add_column(
        "product_spaces",
        sa.Column("target_languages", json_type, nullable=True),
    )

    op.create_unique_constraint(
        "uq_content_final_language_kind",
        "content_products",
        ["final_id", "language", "kind"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_content_final_language_kind", "content_products", type_="unique"
    )
    op.drop_column("product_spaces", "target_languages")
    op.drop_table("content_languages")
