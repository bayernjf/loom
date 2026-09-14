"""M10 config center: config_items + config_item_versions with C2 seed values

Revision ID: 0010_m10_config_center
Revises: 0009_m8_stage11
Create Date: 2026-09-14

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0010_m10_config_center"
down_revision: str | None = "0009_m8_stage11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

_CONFIG_ITEMS = "config_items"
_CONFIG_VERSIONS = "config_item_versions"


def upgrade() -> None:
    op.create_table(
        _CONFIG_ITEMS,
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("category", sa.String(64), nullable=False, index=True),
        sa.Column("value", json_type, nullable=False),
        sa.Column("value_type", sa.String(16), nullable=False),
        sa.Column("validation", json_type, nullable=True),
        sa.Column("source_ref", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        _CONFIG_VERSIONS,
        sa.Column("version_id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(128), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("value", json_type, nullable=False),
        sa.Column("change_note", sa.String(255), nullable=True),
        sa.Column("changed_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("key", "version", name="uq_config_version_key_version"),
    )

    item_rows = [
        {
            "key": key,
            "category": category,
            "value": value,
            "value_type": value_type,
            "validation": validation,
            "source_ref": source_ref,
            "version": 1,
        }
        for key, category, value_type, value, source_ref, validation in CONFIG_SEEDS
    ]
    op.bulk_insert(sa.table(
        _CONFIG_ITEMS,
        sa.column("key", sa.String),
        sa.column("category", sa.String),
        sa.column("value", json_type),
        sa.column("value_type", sa.String),
        sa.column("validation", json_type),
        sa.column("source_ref", sa.String),
        sa.column("version", sa.Integer),
    ), item_rows)

    # 种子即 v1：历史首版可回滚；version_id 用确定性 uuid5（幂等可复现）。
    version_rows = [
        {
            "version_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-config-seed:{key}")),
            "key": key,
            "version": 1,
            "value": value,
            "change_note": "C2 seed",
            "changed_by": None,
        }
        for key, _category, _value_type, value, _source_ref, _validation in CONFIG_SEEDS
    ]
    op.bulk_insert(sa.table(
        _CONFIG_VERSIONS,
        sa.column("version_id", sa.String),
        sa.column("key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("value", json_type),
        sa.column("change_note", sa.String),
        sa.column("changed_by", sa.String),
    ), version_rows)


def downgrade() -> None:
    op.drop_table(_CONFIG_VERSIONS)
    op.drop_table(_CONFIG_ITEMS)
