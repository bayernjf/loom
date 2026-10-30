"""P0: 客户访问令牌表 client_access_tokens（客户内容决策端点鉴权）。

补齐客户侧真实认证与 actor↔tenant 绑定：每行绑定具体租户，库内只存 SHA-256
哈希，明文仅签发时返回一次。纯建表、零种子（令牌由内部运营真实签发）。

Revision ID: 0066_client_access_tokens
Revises: 0065_content_candidates
Create Date: 2026-10-30

"""

import sqlalchemy as sa

from alembic import op

revision: str = "0066_client_access_tokens"
down_revision: str | None = "0065_content_candidates"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "client_access_tokens",
        sa.Column("token_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("client_name", sa.String(128), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(24), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_by", sa.String(64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "key_hash", name="uq_client_access_token_hash"
        ),
    )
    op.create_index(
        "ix_client_access_tokens_tenant_id",
        "client_access_tokens",
        ["tenant_id"],
    )
    op.create_index(
        "ix_client_access_tokens_key_hash",
        "client_access_tokens",
        ["key_hash"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_client_access_tokens_key_hash", table_name="client_access_tokens"
    )
    op.drop_index(
        "ix_client_access_tokens_tenant_id", table_name="client_access_tokens"
    )
    op.drop_table("client_access_tokens")
