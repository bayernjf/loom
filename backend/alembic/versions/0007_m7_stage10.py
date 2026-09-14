"""M7 stage-10 compliance cleaning: CP-LAW domains, law reviews, CCR reports,
wordlist layer column (Q48-Q51)

Revision ID: 0007_m7_stage10
Revises: 0006_m6_stage6
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_m7_stage10"
down_revision: str | None = "0006_m6_stage6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # Q50：词表三层优先序（国家法规 > 平台规则 > 底座默认，不可配置）。M4 存量词条归底座层。
    op.add_column(
        "compliance_wordlist",
        sa.Column(
            "layer",
            sa.String(8),
            nullable=False,
            server_default="base",
        ),
    )

    domains = op.create_table(
        "cp_law_sensitive_domains",
        sa.Column("domain_id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Q48：CP-LAW 敏感领域（领域非词）；line 128/01 §3 段10 六领域种子。
    op.bulk_insert(
        domains,
        [
            {"domain_id": f"cplaw-{code}", "code": code, "name": name}
            for code, name in (
                ("medical", "医疗健康"),
                ("children", "儿童"),
                ("weight_loss", "减肥"),
                ("whitening", "美白"),
                ("medical_device", "医疗器械"),
                ("finance", "金融"),
            )
        ],
    )

    op.create_table(
        "law_reviews",
        sa.Column("law_review_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("product_space_id", sa.String(36), nullable=False, index=True),
        sa.Column("pws_id", sa.String(36), nullable=False, index=True),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("pws_id", name="uq_law_review_pws"),
    )

    op.create_table(
        "ccr_reports",
        sa.Column("ccr_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("product_space_id", sa.String(36), nullable=False, index=True),
        sa.Column("pws_id", sa.String(36), nullable=False, index=True),
        sa.Column("country", sa.String(8), nullable=True, index=True),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("block_required", sa.Boolean(), nullable=False),
        sa.Column("hits", json_type, nullable=False),
        sa.Column("wordlist_context", json_type, nullable=False),
        sa.Column("run_by", sa.String(64), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("ccr_reports")
    op.drop_table("law_reviews")
    op.drop_table("cp_law_sensitive_domains")
    op.drop_column("compliance_wordlist", "layer")
