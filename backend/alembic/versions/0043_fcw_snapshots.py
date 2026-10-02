"""Q251 FCW freeze management (D3.5 segment-6): version snapshots + event log.

Ruling a-f (approved 2026-10-03, docs/02 C1.194):
- (a) granularity = final_id level: one immutable snapshot row per issued
  final_content_whitelist, version constant v1, status frozen on issue;
- (b) rollback semantics = A: revoke current + re-issue a fresh one via E1.1
  (PWS Q32 semantics), never mutate the original row;
- (c) reuse = re-issuance through E1.1 POST /api/fcw/assemble (front-end
  prefills the assembly form), disjoint from the segment-4 candidate-pool copy;
- (d) immutability = runtime guard extended to before_update/before_delete
  (exit_guard.py, Q203 lineage);
- (e) RBAC = require_internal_actor(OPERATIONS), same family as Q242;
- (f) stays V2: engine (tables/guard/revoke endpoint) lands on dev, product
  surface (freeze-management UI) deferred to V2.

New tables mirror pws_snapshots / pws_freeze_logs (migration 0006, Q31/Q32):
fcw_snapshots (final_id FK, version, status=frozen|superseded|revoked,
is_active, snapshot JSON = 6-way input id refs + score + guards at issue,
revoked_by/at/reason); unique (final_id, version).
fcw_freeze_logs (event=freeze|revoke, actor_id, reason detail, append-only).

Revision ID: 0043_fcw_snapshots
Revises: 0042_g1_category_seed
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0043_fcw_snapshots"
down_revision: str | None = "0042_g1_category_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on PostgreSQL, JSON elsewhere (tests), per app/core/db.JSONType.
json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "fcw_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column(
            "final_id",
            sa.String(36),
            sa.ForeignKey("final_content_whitelists.final_id"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("product_space_id", sa.String(36), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("slot_id", sa.String(36), nullable=False),
        sa.Column("goal", sa.String(32), nullable=False),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column("snapshot", json_type, nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_by", sa.String(64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("final_id", "version", name="uq_fcw_final_version"),
    )
    op.create_index("ix_fcw_snapshots_final_id", "fcw_snapshots", ["final_id"])
    op.create_index("ix_fcw_snapshots_tenant_id", "fcw_snapshots", ["tenant_id"])
    op.create_index(
        "ix_fcw_snapshots_product_space_id", "fcw_snapshots", ["product_space_id"]
    )
    op.create_index("ix_fcw_snapshots_status", "fcw_snapshots", ["status"])
    op.create_index("ix_fcw_snapshots_is_active", "fcw_snapshots", ["is_active"])

    op.create_table(
        "fcw_freeze_logs",
        sa.Column("log_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("product_space_id", sa.String(36), nullable=False),
        sa.Column("final_id", sa.String(36), nullable=False),
        sa.Column("event", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(48), nullable=True),
        sa.Column("detail", json_type, nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_fcw_freeze_logs_tenant_id", "fcw_freeze_logs", ["tenant_id"])
    op.create_index(
        "ix_fcw_freeze_logs_product_space_id", "fcw_freeze_logs", ["product_space_id"]
    )
    op.create_index("ix_fcw_freeze_logs_final_id", "fcw_freeze_logs", ["final_id"])


def downgrade() -> None:
    op.drop_index("ix_fcw_freeze_logs_final_id", table_name="fcw_freeze_logs")
    op.drop_index(
        "ix_fcw_freeze_logs_product_space_id", table_name="fcw_freeze_logs"
    )
    op.drop_index("ix_fcw_freeze_logs_tenant_id", table_name="fcw_freeze_logs")
    op.drop_table("fcw_freeze_logs")

    op.drop_index("ix_fcw_snapshots_is_active", table_name="fcw_snapshots")
    op.drop_index("ix_fcw_snapshots_status", table_name="fcw_snapshots")
    op.drop_index(
        "ix_fcw_snapshots_product_space_id", table_name="fcw_snapshots"
    )
    op.drop_index("ix_fcw_snapshots_tenant_id", table_name="fcw_snapshots")
    op.drop_index("ix_fcw_snapshots_final_id", table_name="fcw_snapshots")
    op.drop_table("fcw_snapshots")
