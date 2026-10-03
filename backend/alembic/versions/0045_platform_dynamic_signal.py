"""Q259 (P1-1/P1-2) dynamic signal events + PCP recalc candidates (Q37/Q41/Q42).

Slice 1 of V2-P1 (segment 7/8 weekly recalc loop, docs/08 §2.3):
- platform_dynamic_events: Q37 dynamic signals, ops-registered
  (platform / optional slot / event_type / severity / effective window).
  event_type & severity enums were only in the lost baseline HTML
  【原文未给出，待补】, so no seed — background CRUD only (publish_slots precedent).
- pcp_recalc_candidates: Q41 HumanGate loop — AI produces candidates only,
  ops approves/rejects (approve writes back to pcp_weight_tables and clears
  template_code per Q42 manual-edit semantics). One pending candidate per PCP
  (partial unique index). V1 accepts manual submissions only; the PCP-SCORE
  AI generator stays V2 (model gateway).
- config seed platform.recalc_step = 0.05 (Q42 single-item step cap, knob).

Revision ID: 0045_platform_dynamic_signal
Revises: 0044_video_gen_seed
Create Date: 2026-10-03

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0045_platform_dynamic_signal"
down_revision: str | None = "0044_video_gen_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on PostgreSQL, JSON elsewhere (tests), per app/core/db.JSONType.
json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

_SEED_KEY = "platform.recalc_step"
_SEED = next(row for row in CONFIG_SEEDS if row[0] == _SEED_KEY)


def upgrade() -> None:
    op.create_table(
        "platform_dynamic_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("slot_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("effective_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(512), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_platform_dynamic_events_platform", "platform_dynamic_events", ["platform"])
    op.create_index("ix_platform_dynamic_events_slot_id", "platform_dynamic_events", ["slot_id"])

    op.create_table(
        "pcp_recalc_candidates",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column(
            "pcp_id",
            sa.String(36),
            sa.ForeignKey("pcp_weight_tables.pcp_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("product_space_id", sa.String(36), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("proposed_weights", json_type, nullable=False),
        sa.Column("change_list", json_type, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rejected_reason", sa.String(512), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.String(64), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pcp_recalc_candidates_pcp_id", "pcp_recalc_candidates", ["pcp_id"])
    op.create_index("ix_pcp_recalc_candidates_status", "pcp_recalc_candidates", ["status"])
    op.create_index("ix_pcp_recalc_candidates_tenant_id", "pcp_recalc_candidates", ["tenant_id"])
    op.create_index(
        "uq_pcp_recalc_pending",
        "pcp_recalc_candidates",
        ["pcp_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    # Config seed: Q42 single-item recalc step (idempotent, 0041 pattern).
    bind = op.get_bind()
    config_items_t = sa.table(
        "config_items",
        sa.column("key", sa.String),
        sa.column("category", sa.String),
        sa.column("value", json_type),
        sa.column("value_type", sa.String),
        sa.column("validation", json_type),
        sa.column("source_ref", sa.String),
        sa.column("version", sa.Integer),
    )
    config_versions_t = sa.table(
        "config_item_versions",
        sa.column("version_id", sa.String),
        sa.column("key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("value", json_type),
        sa.column("change_note", sa.String),
        sa.column("changed_by", sa.String),
    )
    key, category, value_type, value, source_ref, validation = _SEED
    bind.execute(
        postgresql.insert(config_items_t).on_conflict_do_nothing(),
        [{
            "key": key,
            "category": category,
            "value": value,
            "value_type": value_type,
            "validation": validation,
            "source_ref": source_ref,
            "version": 1,
        }],
    )
    bind.execute(
        postgresql.insert(config_versions_t).on_conflict_do_nothing(),
        [{
            "version_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-config-seed:{key}")),
            "key": key,
            "version": 1,
            "value": value,
            "change_note": "Q259 seed",
            "changed_by": None,
        }],
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM config_item_versions WHERE key = '{_SEED_KEY}'")
    op.execute(f"DELETE FROM config_items WHERE key = '{_SEED_KEY}'")
    op.drop_index("uq_pcp_recalc_pending", table_name="pcp_recalc_candidates")
    op.drop_index("ix_pcp_recalc_candidates_status", table_name="pcp_recalc_candidates")
    op.drop_index("ix_pcp_recalc_candidates_tenant_id", table_name="pcp_recalc_candidates")
    op.drop_index("ix_pcp_recalc_candidates_pcp_id", table_name="pcp_recalc_candidates")
    op.drop_table("pcp_recalc_candidates")
    op.drop_index("ix_platform_dynamic_events_slot_id", table_name="platform_dynamic_events")
    op.drop_index("ix_platform_dynamic_events_platform", table_name="platform_dynamic_events")
    op.drop_table("platform_dynamic_events")
