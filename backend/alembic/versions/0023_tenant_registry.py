"""Q95 tenant registry: tenants table + backfill of existing tenant_id values.

Existing business rows are preserved: every distinct tenant_id found in
product_intake_applications / product_spaces is backfilled as plan=basic,
status=active with detail {'backfilled': true}. The segment-1 admission gate
is application-layer only — no hard foreign key is added to existing tables.

Revision ID: 0023_tenant_registry
Revises: 0022_review_sla_hours
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023_tenant_registry"
down_revision: str | None = "0022_review_sla_hours"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

_BACKFILL_SOURCES = ("product_intake_applications", "product_spaces")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column(
            "plan", sa.String(length=16), nullable=False, server_default="trial"
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="trial"
        ),
        sa.Column("monthly_token_quota", sa.Integer(), nullable=True),
        sa.Column("detail", json_type, nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("plan_changed_by", sa.String(length=64), nullable=True),
        sa.Column("plan_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_by", sa.String(length=64), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tenants_status", "tenants", ["status"])

    bind = op.get_bind()
    tenant_ids: set[str] = set()
    for table_name in _BACKFILL_SOURCES:
        source = sa.table(table_name, sa.column("tenant_id", sa.String(length=64)))
        rows = bind.execute(sa.select(source.c.tenant_id).distinct()).fetchall()
        tenant_ids.update(row[0] for row in rows if row[0])

    if tenant_ids:
        tenants = sa.table(
            "tenants",
            sa.column("tenant_id", sa.String(length=64)),
            sa.column("plan", sa.String(length=16)),
            sa.column("status", sa.String(length=16)),
            sa.column("detail", json_type),
            sa.column("created_by", sa.String(length=64)),
        )
        bind.execute(
            tenants.insert(),
            [
                {
                    "tenant_id": tenant_id,
                    "plan": "basic",
                    "status": "active",
                    "detail": {
                        "backfilled": True,
                        "reason": "0023 pre-registry tenant_id backfill",
                    },
                    "created_by": "system-migration-0023",
                }
                for tenant_id in sorted(tenant_ids)
            ],
        )


def downgrade() -> None:
    op.drop_index("ix_tenants_status", table_name="tenants")
    op.drop_table("tenants")
