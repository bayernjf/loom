"""Q325: backfill candidate data ratified by the owner (02 C1.268).

Four pure-data operations across three tables, all sourced from
`docs/design-q324-candidate-review.md` §10 (owner ratified "按推荐" on 2026-10-09):

1. `downgrade_actions`  — backfill `name`/`why` for the six Q38 codes
   (`DOWNGRADE_ACTION_META`, previously NULL per migration 0051).
2. `pool_options`      — backfill `options` for the 17 Q43 pools
   (`POOL_OPTION_CANDIDATES`, previously empty arrays per migration 0052).
3. `fp_source_routes`  — add the 7th DIM-SOURCE route `case_evidence`
   (Q8 seeded six routes in migration 0003; the 7th was missing in the spec
   and is now ratified as `case_evidence` with sort_order 7).
4. Tenant plans/quota  — no DB change needed: `plan` is a plain String(16)
   column and quotas live in code constants (`tenants/models.py`).

Revision ID: 0053_q325_candidate_backfill
Revises: 0052_pool_options
Create Date: 2026-10-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.downgrade_actions.seeds import DOWNGRADE_ACTION_META
from app.core.pool_options.seeds import POOL_OPTION_CANDIDATES

revision: str = "0053_q325_candidate_backfill"
down_revision: str | None = "0052_pool_options"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Q38 六码 name/why 回填（工程候选文案，运营可在管理面微调）。
    for code, meta in DOWNGRADE_ACTION_META.items():
        op.execute(
            sa.text(
                "UPDATE downgrade_actions SET name = :name, why = :why "
                "WHERE code = :code"
            ).bindparams(
                sa.bindparam("name", meta["name"]),
                sa.bindparam("why", meta["why"]),
                sa.bindparam("code", code),
            )
        )

    # 2) Q43 17 池候选值回填（池名闭合集＝WEIGHT_KEYS_17；goal 池已闭环不入本表）。
    for pool, options in POOL_OPTION_CANDIDATES.items():
        op.execute(
            sa.text(
                "UPDATE pool_options SET options = :options "
                "WHERE pool = :pool"
            ).bindparams(
                sa.bindparam("options", options),
                sa.bindparam("pool", pool),
            )
        )

    # 3) DIM-SOURCE 第 7 路 case_evidence（Q325 拍板甲案；消费方 field_plan.py 动态读 enabled 路由）。
    op.execute(
        sa.text(
            "INSERT INTO fp_source_routes (route, name, enabled, sort_order) "
            "VALUES (:route, :name, :enabled, :sort_order) "
            "ON CONFLICT (route) DO NOTHING"
        ).bindparams(
            sa.bindparam("route", "case_evidence"),
            sa.bindparam("name", "案例证据/同类好内容案例"),
            sa.bindparam("enabled", True),
            sa.bindparam("sort_order", 7),
        )
    )


def downgrade() -> None:
    # 1) name/why 回到 NULL（0051 原状）。
    op.execute(
        sa.text(
            "UPDATE downgrade_actions SET name = NULL, why = NULL "
            "WHERE code IN :codes"
        ).bindparams(sa.bindparam("codes", list(DOWNGRADE_ACTION_META), expanding=True))
    )
    # 2) options 回到空数组（0052 原状）。
    op.execute(
        sa.text(
            "UPDATE pool_options SET options = :empty WHERE pool IN :pools"
        ).bindparams(
            sa.bindparam("empty", []),
            sa.bindparam("pools", list(POOL_OPTION_CANDIDATES), expanding=True),
        )
    )
    # 3) 移除第 7 路。
    op.execute(sa.text("DELETE FROM fp_source_routes WHERE route = 'case_evidence'"))
