"""Q83 PWC-BUILDER real-LLM slice: seed ai_scene_routes PWC-BUILDER -> synthetic
model and PWC-BUILDER prompt v0.1. Data-only migration, no schema change.

Revision ID: 0015_pwc_builder_seed
Revises: 0014_model_gateway
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.model_registry.seeds import (
    PWC_BUILDER_PROMPT_ID,
    PWC_BUILDER_PROMPT_TEMPLATE,
    PWC_BUILDER_PROMPT_VARIABLES,
    PWC_BUILDER_PROMPT_VERSION,
    SCENE_PWC_BUILDER,
    SYNTHETIC_MODEL_ID,
)

revision: str = "0015_pwc_builder_seed"
down_revision: str | None = "0014_model_gateway"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ai_scene_routes = sa.table(
        "ai_scene_routes",
        sa.column("scene", sa.String), sa.column("model_id", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(ai_scene_routes, [{
        "scene": SCENE_PWC_BUILDER, "model_id": SYNTHETIC_MODEL_ID,
        "updated_by": "_migration_seed",
    }])

    skill_prompts = sa.table(
        "skill_prompts",
        sa.column("skill_id", sa.String), sa.column("current_version", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(skill_prompts, [{
        "skill_id": SCENE_PWC_BUILDER, "current_version": PWC_BUILDER_PROMPT_VERSION,
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
        "version_id": PWC_BUILDER_PROMPT_ID,
        "skill_id": SCENE_PWC_BUILDER,
        "version": PWC_BUILDER_PROMPT_VERSION,
        "template": PWC_BUILDER_PROMPT_TEMPLATE,
        "variables": PWC_BUILDER_PROMPT_VARIABLES,
        "created_by": "_migration_seed",
    }])


def downgrade() -> None:
    op.execute(
        f"DELETE FROM skill_prompt_versions WHERE skill_id = '{SCENE_PWC_BUILDER}'"
    )
    op.execute(f"DELETE FROM skill_prompts WHERE skill_id = '{SCENE_PWC_BUILDER}'")
    op.execute(f"DELETE FROM ai_scene_routes WHERE scene = '{SCENE_PWC_BUILDER}'")
