"""Q79-4 skill7 dual anchor: nullable intake_id on skill_runs/skill_candidates,
skill_candidates.product_space_id becomes nullable (WF-01 段2 predates ProductSpace).

Revision ID: 0013_skill7_intake_anchor
Revises: 0012_m10_skill7
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_skill7_intake_anchor"
down_revision: str | None = "0012_m10_skill7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SKILL_RUNS = "skill_runs"
_SKILL_CANDIDATES = "skill_candidates"


def upgrade() -> None:
    op.add_column(
        _SKILL_RUNS,
        sa.Column("intake_id", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_skill_runs_intake_id", _SKILL_RUNS, ["intake_id"])
    op.add_column(
        _SKILL_CANDIDATES,
        sa.Column("intake_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_skill_candidates_intake_id", _SKILL_CANDIDATES, ["intake_id"]
    )
    # 历史数据全部为 PS 锚点（WF-04/WF-02）；Q79 起 c1_recognition 走 intake 锚点。
    op.alter_column(
        _SKILL_CANDIDATES, "product_space_id", existing_type=sa.String(length=36),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        _SKILL_CANDIDATES, "product_space_id", existing_type=sa.String(length=36),
        nullable=False,
    )
    op.drop_index("ix_skill_candidates_intake_id", table_name=_SKILL_CANDIDATES)
    op.drop_column(_SKILL_CANDIDATES, "intake_id")
    op.drop_index("ix_skill_runs_intake_id", table_name=_SKILL_RUNS)
    op.drop_column(_SKILL_RUNS, "intake_id")
