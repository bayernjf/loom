"""L-07 第三路 DIM-SOURCE connector：建 case_evidence 表 + 发布 DIM-MERGE v0.5。

建 `case_evidence`：案例证据/同类好内容案例（第 7 路来源本体），两层——
通用层（product_space_id 为 NULL）／产品专属层（绑定 product_space_id）。
同 0060 inspiration_entries 纪律：纯建表、零种子，内容由运营真实填充。

同时发布 DIM-MERGE Prompt v0.5（在 v0.4 基础上追加
``$case_evidence_entries`` 与 ``case_evidence:<case_id>`` 依据说明）；
存量库若已有 v0.5 则跳过插入，仅把 current_version 指到 v0.5。

Revision ID: 0070_case_evidence_dim_merge_v05
Revises: 0069_dim_merge_compliance_risk_prompt
Create Date: 2026-11-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.model_registry.seeds import (
    DIM_MERGE_PROMPT_CASE_EVIDENCE_ID,
    DIM_MERGE_PROMPT_CASE_EVIDENCE_TEMPLATE,
    DIM_MERGE_PROMPT_CASE_EVIDENCE_VARIABLES,
    DIM_MERGE_PROMPT_CASE_EVIDENCE_VERSION,
    SCENE_DIM_MERGE,
)

revision: str = "0070_case_evidence_dim_merge_v05"
down_revision: str | None = "0069_dim_merge_compliance_risk_prompt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_evidence",
        sa.Column("case_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("product_space_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_case_evidence_tenant_id", "case_evidence", ["tenant_id"])
    op.create_index(
        "ix_case_evidence_product_space_id",
        "case_evidence",
        ["product_space_id"],
    )

    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM skill_prompt_versions "
            "WHERE skill_id = :skill_id AND version = :version"
        ),
        {
            "skill_id": SCENE_DIM_MERGE,
            "version": DIM_MERGE_PROMPT_CASE_EVIDENCE_VERSION,
        },
    ).first()
    if exists is None:
        skill_prompt_versions = sa.table(
            "skill_prompt_versions",
            sa.column("version_id", sa.String),
            sa.column("skill_id", sa.String),
            sa.column("version", sa.String),
            sa.column("template", sa.Text),
            sa.column("change_note", sa.Text),
            sa.column("variables", postgresql.JSONB(astext_type=sa.Text())),
            sa.column("created_by", sa.String),
        )
        op.bulk_insert(skill_prompt_versions, [{
            "version_id": DIM_MERGE_PROMPT_CASE_EVIDENCE_ID,
            "skill_id": SCENE_DIM_MERGE,
            "version": DIM_MERGE_PROMPT_CASE_EVIDENCE_VERSION,
            "template": DIM_MERGE_PROMPT_CASE_EVIDENCE_TEMPLATE,
            "change_note": "L-07 case_evidence connector",
            "variables": DIM_MERGE_PROMPT_CASE_EVIDENCE_VARIABLES,
            "created_by": "_migration_seed",
        }])

    bind.execute(
        sa.text(
            "UPDATE skill_prompts SET current_version = :version, "
            "updated_by = '_migration_seed', updated_at = now() "
            "WHERE skill_id = :skill_id"
        ),
        {
            "version": DIM_MERGE_PROMPT_CASE_EVIDENCE_VERSION,
            "skill_id": SCENE_DIM_MERGE,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM skill_prompt_versions "
            "WHERE skill_id = :skill_id AND version = :version"
        ),
        {
            "skill_id": SCENE_DIM_MERGE,
            "version": DIM_MERGE_PROMPT_CASE_EVIDENCE_VERSION,
        },
    )
    bind.execute(
        sa.text(
            "UPDATE skill_prompts SET current_version = :version, "
            "updated_by = '_migration_seed', updated_at = now() "
            "WHERE skill_id = :skill_id"
        ),
        {
            "version": "v0.4",
            "skill_id": SCENE_DIM_MERGE,
        },
    )
    op.drop_index(
        "ix_case_evidence_product_space_id", table_name="case_evidence"
    )
    op.drop_index("ix_case_evidence_tenant_id", table_name="case_evidence")
    op.drop_table("case_evidence")
