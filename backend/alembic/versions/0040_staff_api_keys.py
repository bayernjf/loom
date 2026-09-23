"""Q178 internal staff personal access tokens (PAT).

New table staff_api_keys backs the first identity-layer slice (PAT, plan A decided
by the owner on 2026-09-24): each row is a revocable personal token bound to a
specific internal operator (staff_id/staff_name) with a snapshot of internal
roles. Separate domain from agent_api_keys (Q88, machine/Agent credentials):
- only SHA-256 hashes are stored (plaintext returned once at issue);
- roles stored as JSONB on PostgreSQL / JSON elsewhere (db.JSONType);
- same staff_id may hold multiple rows for rotation; revoke is per key_id.

Gated by LOOM_STAFF_AUTH_ENABLED (default off): when off, management endpoints
keep the V1 self-asserted actor behavior and this table simply stays unused.

Revision ID: 0040_staff_api_keys
Revises: 0039_import_jobs
Create Date: 2026-09-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0040_staff_api_keys"
down_revision: str | None = "0039_import_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on PostgreSQL, JSON elsewhere (tests), per app/core/db.JSONType.
json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "staff_api_keys",
        sa.Column("key_id", sa.String(36), primary_key=True),
        sa.Column("staff_id", sa.String(64), nullable=False),
        sa.Column("staff_name", sa.String(128), nullable=False),
        sa.Column("roles", json_type, nullable=False),
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
        sa.UniqueConstraint("key_hash", name="uq_staff_api_key_hash"),
    )
    op.create_index("ix_staff_api_keys_staff_id", "staff_api_keys", ["staff_id"])
    op.create_index("ix_staff_api_keys_key_hash", "staff_api_keys", ["key_hash"])


def downgrade() -> None:
    op.drop_index("ix_staff_api_keys_key_hash", table_name="staff_api_keys")
    op.drop_index("ix_staff_api_keys_staff_id", table_name="staff_api_keys")
    op.drop_table("staff_api_keys")
