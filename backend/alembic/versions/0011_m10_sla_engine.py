"""M10b SLA engine: compliance_wordlist.activated_at for future-effective Q51 scan

Revision ID: 0011_m10_sla_engine
Revises: 0010_m10_config_center
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_m10_sla_engine"
down_revision: str | None = "0010_m10_config_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "compliance_wordlist",
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 存量 active 词条视为建列时刻即已生效（未给未来生效期，无漏扫风险）。
    op.execute(
        "UPDATE compliance_wordlist SET activated_at = now() "
        "WHERE status = 'active' AND activated_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("compliance_wordlist", "activated_at")
