"""M10e skill7 channel: skill_runs (append-only SkillRunLog) + skill_candidates

Revision ID: 0012_m10_skill7
Revises: 0011_m10_sla_engine
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_m10_skill7"
down_revision: str | None = "0011_m10_sla_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

_SKILL_RUNS = "skill_runs"
_SKILL_CANDIDATES = "skill_candidates"


def upgrade() -> None:
    op.create_table(
        _SKILL_RUNS,
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("skill_id", sa.String(64), nullable=False, index=True),
        sa.Column("wf_id", sa.String(16), nullable=True),
        sa.Column("tenant_id", sa.String(36), nullable=True, index=True),
        sa.Column("product_space_id", sa.String(36), nullable=True, index=True),
        # requested=系统触发无产出（Q71 补货）；succeeded/failed=投递终结态。
        sa.Column("status", sa.String(16), nullable=False, index=True),
        # delivery=外部投递（operations）；restock_auto=消费触发补货（system）。
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("input", json_type, nullable=True),
        sa.Column("output", json_type, nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
        comment="SkillRunLog append-only; history must never be mutated (PT-COMPLIANCE-V2.0)",
    )
    op.create_table(
        _SKILL_CANDIDATES,
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, index=True),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.String(64), nullable=False, index=True),
        sa.Column("wf_id", sa.String(16), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=True, index=True),
        sa.Column("product_space_id", sa.String(36), nullable=False, index=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        # pending_review/confirmed/modified/rejected/applied/archived（05 §2.3）
        sa.Column("state", sa.String(16), nullable=False, index=True),
        sa.Column("applied_refs", json_type, nullable=True),
        sa.Column(
            "human_modified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
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
            "run_id", "candidate_index", name="uq_skill_candidate_run_index"
        ),
    )


def downgrade() -> None:
    op.drop_table(_SKILL_CANDIDATES)
    op.drop_table(_SKILL_RUNS)
