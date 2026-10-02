"""V1 engine prep slice: seed ai_scene_routes VIDEO-GEN -> synthetic model and
VIDEO-GEN prompt v0.1. Data-only migration, no schema change.

Revision ID: 0044_video_gen_seed
Revises: 0043_fcw_snapshots
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.model_registry.seeds import (
    SCENE_VIDEO_GEN,
    SYNTHETIC_MODEL_ID,
    VIDEO_GEN_PROMPT_ID,
    VIDEO_GEN_PROMPT_TEMPLATE,
    VIDEO_GEN_PROMPT_VARIABLES,
    VIDEO_GEN_PROMPT_VERSION,
)

revision: str = "0044_video_gen_seed"
down_revision: str | None = "0043_fcw_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ai_scene_routes = sa.table(
        "ai_scene_routes",
        sa.column("scene", sa.String), sa.column("model_id", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(ai_scene_routes, [{
        "scene": SCENE_VIDEO_GEN, "model_id": SYNTHETIC_MODEL_ID,
        "updated_by": "_migration_seed",
    }])

    skill_prompts = sa.table(
        "skill_prompts",
        sa.column("skill_id", sa.String), sa.column("current_version", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(skill_prompts, [{
        "skill_id": SCENE_VIDEO_GEN, "current_version": VIDEO_GEN_PROMPT_VERSION,
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
        "version_id": VIDEO_GEN_PROMPT_ID,
        "skill_id": SCENE_VIDEO_GEN,
        "version": VIDEO_GEN_PROMPT_VERSION,
        "template": VIDEO_GEN_PROMPT_TEMPLATE,
        "variables": VIDEO_GEN_PROMPT_VARIABLES,
        "created_by": "_migration_seed",
    }])


def downgrade() -> None:
    op.execute(
        f"DELETE FROM skill_prompt_versions WHERE skill_id = '{SCENE_VIDEO_GEN}'"
    )
    op.execute(f"DELETE FROM skill_prompts WHERE skill_id = '{SCENE_VIDEO_GEN}'")
    op.execute(f"DELETE FROM ai_scene_routes WHERE scene = '{SCENE_VIDEO_GEN}'")
