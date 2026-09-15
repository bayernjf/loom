"""Q88 inbound Agent API keys: one key per external Agent, revocable,
SHA-256 hashed (inbound only needs comparison, unlike outbound Fernet keys).

Key half only — POST /api/effect-callback and effect data land with stage 13
(P3/V2), see 05 §1.1.1 and 02 C1.32.

Revision ID: 0019_agent_api_keys
Revises: 0018_atom_affinity_embedding
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_agent_api_keys"
down_revision: str | None = "0018_atom_affinity_embedding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_api_keys",
        sa.Column("key_id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_by", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_agent_api_key_hash"),
    )
    op.create_index("ix_agent_api_keys_key_hash", "agent_api_keys", ["key_hash"])


def downgrade() -> None:
    op.drop_index("ix_agent_api_keys_key_hash", table_name="agent_api_keys")
    op.drop_table("agent_api_keys")
