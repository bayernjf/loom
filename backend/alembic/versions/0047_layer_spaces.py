"""Q262 (P2 slice) layerSpaces shared base (Q46).

V2-P2 first slice (docs/08 §2.3, Q46): the cross-product shared content base
that CSP/CSTP/CEP atoms come from (docs/01 line 1261, docs/04 §2.16).
Design-draft entities per docs/10 §2.5 ("implementation follows V2/V3").

- layer_spaces: the four layers (strategy/structure/expression/compliance)
  with their full dimension-name lists (docs/04 §2.16, "维度名完整");
  22 dimension names are seeded verbatim from the docs — values are
  【原文未给出，待补】 and are NOT seeded (publish_slots precedent).
- layer_space_items: the atom pool (one row per dimension value), carrying
  docs/10's suggested candidate/formal/frozen pool states plus archived
  (soft-delete, dictionary precedent). Shared table — no tenant_id (Q46:
  "internal 命名空间", cross-tenant).

Q46 guardrails: writes are platform_admin-only; impact preview
("被 N 个活跃配方引用") before mutating referenced atoms; audit on every write.

Revision ID: 0047_layer_spaces
Revises: 0046_platform_adapter_seed
Create Date: 2026-10-03

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.decision.layer_strategy.seeds import LAYER_DIMENSIONS

revision: str = "0047_layer_spaces"
down_revision: str | None = "0046_platform_adapter_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on PostgreSQL, JSON elsewhere (tests), per app/core/db.JSONType.
json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "layer_spaces",
        sa.Column("layer_id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("dimensions", json_type, nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "layer_space_items",
        sa.Column("item_id", sa.String(36), primary_key=True),
        sa.Column("layer_id", sa.String(36), nullable=False, index=True),
        sa.Column("dimension", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            onupdate=sa.func.now(),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "layer_id", "dimension", "name", name="uq_layer_space_item_identity"
        ),
    )

    layer_spaces = sa.table(
        "layer_spaces",
        sa.column("layer_id", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("dimensions", json_type),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        layer_spaces,
        [
            {
                "layer_id": str(uuid.uuid4()),
                "code": code,
                "name": name,
                "dimensions": list(dims),
                "sort_order": order,
            }
            for order, (code, (name, dims)) in enumerate(
                LAYER_DIMENSIONS.items(), start=1
            )
        ],
    )


def downgrade() -> None:
    op.drop_table("layer_space_items")
    op.drop_table("layer_spaces")
