"""M4/T-M4-02: 内容底座通用候选表 content_candidates。

不绑 PWS/intake/workflow；状态机与 skill7 候选同构
（pending_review→confirmed/modified/rejected）。纯建表、零种子
（内容由真实请求/模型产出，不放假数据）。

Revision ID: 0065_content_candidates
Revises: 0064_field_candidate_gate_sla_seed
Create Date: 2026-10-22

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0065_content_candidates"
down_revision: str | None = "0064_field_candidate_gate_sla_seed"
branch_labels: str | None = None
depends_on: str | None = None


def _json() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "content_candidates",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("product_id", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("body", _json(), nullable=False),
        sa.Column("evidence_refs", _json(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("final_body", _json(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_content_candidates_idempotency_key"
        ),
    )
    op.create_index(
        "ix_content_candidates_product_id",
        "content_candidates",
        ["product_id"],
    )
    op.create_index(
        "ix_content_candidates_status", "content_candidates", ["status"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_content_candidates_status", table_name="content_candidates"
    )
    op.drop_index(
        "ix_content_candidates_product_id", table_name="content_candidates"
    )
    op.drop_table("content_candidates")
