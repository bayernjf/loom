"""Q85 WF-02 field-plan (DIM-MERGE) real-LLM slice: seed ai_scene_routes
DIM-MERGE -> synthetic model and DIM-MERGE prompt v0.1. Data-only migration,
no schema change.

Revision ID: 0017_dim_merge_seed
Revises: 0016_type_match_seed
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.model_registry.seeds import (
    DIM_MERGE_PROMPT_ID,
    DIM_MERGE_PROMPT_TEMPLATE,
    DIM_MERGE_PROMPT_VARIABLES,
    DIM_MERGE_PROMPT_VERSION,
    SCENE_DIM_MERGE,
    SYNTHETIC_MODEL_ID,
)

revision: str = "0017_dim_merge_seed"
down_revision: str | None = "0016_type_match_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ai_scene_routes = sa.table(
        "ai_scene_routes",
        sa.column("scene", sa.String), sa.column("model_id", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(ai_scene_routes, [{
        "scene": SCENE_DIM_MERGE, "model_id": SYNTHETIC_MODEL_ID,
        "updated_by": "_migration_seed",
    }])

    skill_prompts = sa.table(
        "skill_prompts",
        sa.column("skill_id", sa.String), sa.column("current_version", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(skill_prompts, [{
        "skill_id": SCENE_DIM_MERGE, "current_version": DIM_MERGE_PROMPT_VERSION,
        "updated_by": "_migration_seed",
    }])

    skill_prompt_versions = sa.table(
        "skill_prompt_versions",
        sa.column("version_id", sa.String), sa.column("skill_id", sa.String),
        sa.column("version", sa.String), sa.column("template", sa.Text),
        sa.column("variables", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("created_by", sa.String),
    )
    op.bulk_insert(skill_prompt_versions, [{
        "version_id": DIM_MERGE_PROMPT_ID,
        "skill_id": SCENE_DIM_MERGE,
        "version": DIM_MERGE_PROMPT_VERSION,
        "template": DIM_MERGE_PROMPT_TEMPLATE,
        "variables": DIM_MERGE_PROMPT_VARIABLES,
        "created_by": "_migration_seed",
    }])


def downgrade() -> None:
    op.execute(
        f"DELETE FROM skill_prompt_versions WHERE skill_id = '{SCENE_DIM_MERGE}'"
    )
    op.execute(f"DELETE FROM skill_prompts WHERE skill_id = '{SCENE_DIM_MERGE}'")
    op.execute(f"DELETE FROM ai_scene_routes WHERE scene = '{SCENE_DIM_MERGE}'")
