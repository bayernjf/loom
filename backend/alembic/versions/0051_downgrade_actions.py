"""Q306: Q38 downgrade-action dictionary carrier (docs/02:141, docs/10 §dict_management).

New table `downgrade_actions` seeded with the six codes from the user's own words
(REMOVE_BRAND / REMOVE_CLAIM / REMOVE_LINK / SOFT_CTA / SHORTEN / SUBST_WORD —
the docs/10 wording drift was corrected by Q295 on 2026-10-06). Same shape as the
sibling dictionaries: code PK + status + timestamps, soft archive, CRUD + audit.
`name`/`why` stay NULL in the seed — the spec gives no Chinese labels and inventing
business text is out of bounds; ops fills them through the admin surface.

Revision ID: 0051_downgrade_actions
Revises: 0050_platform_adapter_candidates
Create Date: 2026-10-07

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.downgrade_actions.seeds import DOWNGRADE_ACTION_CODES

revision: str = "0051_downgrade_actions"
down_revision: str | None = "0050_platform_adapter_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    downgrade_actions = op.create_table(
        "downgrade_actions",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("why", sa.String(256), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
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
    op.create_index(
        "ix_downgrade_actions_status", "downgrade_actions", ["status"]
    )
    op.bulk_insert(
        downgrade_actions,
        [{"code": code} for code in DOWNGRADE_ACTION_CODES],
    )


def downgrade() -> None:
    op.drop_index("ix_downgrade_actions_status", table_name="downgrade_actions")
    op.drop_table("downgrade_actions")
