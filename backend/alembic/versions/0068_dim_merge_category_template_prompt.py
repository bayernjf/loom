"""L-07 单路 DIM-SOURCE connector：发布 DIM-MERGE Prompt v0.3。

v0.3 只追加 ``$category_template_entries`` 与 ``category_template:<fid>``
依据说明；存量库若已有 v0.3 则跳过插入，仅把 current_version 指到 v0.3。
本迁移不改 schema。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.model_registry.seeds import (
    DIM_MERGE_PROMPT_CATEGORY_ID,
    DIM_MERGE_PROMPT_CATEGORY_TEMPLATE,
    DIM_MERGE_PROMPT_CATEGORY_VARIABLES,
    DIM_MERGE_PROMPT_CATEGORY_VERSION,
    SCENE_DIM_MERGE,
)

revision: str = "0068_dim_merge_category_template_prompt"
down_revision: str | None = "0067_content_goal_ratio_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM skill_prompt_versions "
            "WHERE skill_id = :skill_id AND version = :version"
        ),
        {
            "skill_id": SCENE_DIM_MERGE,
            "version": DIM_MERGE_PROMPT_CATEGORY_VERSION,
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
            "version_id": DIM_MERGE_PROMPT_CATEGORY_ID,
            "skill_id": SCENE_DIM_MERGE,
            "version": DIM_MERGE_PROMPT_CATEGORY_VERSION,
            "template": DIM_MERGE_PROMPT_CATEGORY_TEMPLATE,
            "change_note": "L-07 category_template connector",
            "variables": DIM_MERGE_PROMPT_CATEGORY_VARIABLES,
            "created_by": "_migration_seed",
        }])

    bind.execute(
        sa.text(
            "UPDATE skill_prompts SET current_version = :version, "
            "updated_by = '_migration_seed', updated_at = now() "
            "WHERE skill_id = :skill_id"
        ),
        {
            "version": DIM_MERGE_PROMPT_CATEGORY_VERSION,
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
            "version": DIM_MERGE_PROMPT_CATEGORY_VERSION,
        },
    )
    bind.execute(
        sa.text(
            "UPDATE skill_prompts SET current_version = COALESCE(("
            "SELECT version FROM skill_prompt_versions "
            "WHERE skill_id = :skill_id "
            "ORDER BY created_at DESC, version_id DESC LIMIT 1"
            "), 'v0.1'), updated_by = '_migration_seed', updated_at = now() "
            "WHERE skill_id = :skill_id"
        ),
        {"skill_id": SCENE_DIM_MERGE},
    )
