"""WF-07 AI selection skills: seed four PT scene routes (PT-CONTENT-GOAL-PLAN,
PT-STRUCT-MATCH, PT-TONE-STYLE, PT-CONTENT-GOAL-TAG) -> synthetic model and
their prompt v0.1. Data-only migration, no schema change.

Revision ID: 0054_wf07_skill_scene_seed
Revises: 0053_q325_candidate_backfill
Create Date: 2026-10-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.model_registry.seeds import (
    PT_CONTENT_GOAL_PLAN_PROMPT_ID,
    PT_CONTENT_GOAL_PLAN_TEMPLATE,
    PT_CONTENT_GOAL_PLAN_VARIABLES,
    PT_CONTENT_GOAL_PLAN_VERSION,
    PT_CONTENT_GOAL_TAG_PROMPT_ID,
    PT_CONTENT_GOAL_TAG_TEMPLATE,
    PT_CONTENT_GOAL_TAG_VARIABLES,
    PT_CONTENT_GOAL_TAG_VERSION,
    PT_STRUCT_MATCH_PROMPT_ID,
    PT_STRUCT_MATCH_TEMPLATE,
    PT_STRUCT_MATCH_VARIABLES,
    PT_STRUCT_MATCH_VERSION,
    PT_TONE_STYLE_PROMPT_ID,
    PT_TONE_STYLE_TEMPLATE,
    PT_TONE_STYLE_VARIABLES,
    PT_TONE_STYLE_VERSION,
    SCENE_PT_CONTENT_GOAL_PLAN,
    SCENE_PT_CONTENT_GOAL_TAG,
    SCENE_PT_STRUCT_MATCH,
    SCENE_PT_TONE_STYLE,
    SYNTHETIC_MODEL_ID,
)

revision: str = "0054_wf07_skill_scene_seed"
down_revision: str | None = "0053_q325_candidate_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (scene, version, prompt_id, template, variables)
_SCENES = (
    (SCENE_PT_CONTENT_GOAL_PLAN, PT_CONTENT_GOAL_PLAN_VERSION,
     PT_CONTENT_GOAL_PLAN_PROMPT_ID, PT_CONTENT_GOAL_PLAN_TEMPLATE,
     PT_CONTENT_GOAL_PLAN_VARIABLES),
    (SCENE_PT_STRUCT_MATCH, PT_STRUCT_MATCH_VERSION,
     PT_STRUCT_MATCH_PROMPT_ID, PT_STRUCT_MATCH_TEMPLATE,
     PT_STRUCT_MATCH_VARIABLES),
    (SCENE_PT_TONE_STYLE, PT_TONE_STYLE_VERSION,
     PT_TONE_STYLE_PROMPT_ID, PT_TONE_STYLE_TEMPLATE,
     PT_TONE_STYLE_VARIABLES),
    (SCENE_PT_CONTENT_GOAL_TAG, PT_CONTENT_GOAL_TAG_VERSION,
     PT_CONTENT_GOAL_TAG_PROMPT_ID, PT_CONTENT_GOAL_TAG_TEMPLATE,
     PT_CONTENT_GOAL_TAG_VARIABLES),
)


def upgrade() -> None:
    ai_scene_routes = sa.table(
        "ai_scene_routes",
        sa.column("scene", sa.String), sa.column("model_id", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(ai_scene_routes, [
        {"scene": scene, "model_id": SYNTHETIC_MODEL_ID,
         "updated_by": "_migration_seed"}
        for scene, *_ in _SCENES
    ])

    skill_prompts = sa.table(
        "skill_prompts",
        sa.column("skill_id", sa.String), sa.column("current_version", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(skill_prompts, [
        {"skill_id": scene, "current_version": version,
         "updated_by": "_migration_seed"}
        for scene, version, *_ in _SCENES
    ])

    skill_prompt_versions = sa.table(
        "skill_prompt_versions",
        sa.column("version_id", sa.String), sa.column("skill_id", sa.String),
        sa.column("version", sa.String), sa.column("template", sa.Text),
        sa.column("variables", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("created_by", sa.String),
    )
    op.bulk_insert(skill_prompt_versions, [
        {
            "version_id": prompt_id,
            "skill_id": scene,
            "version": version,
            "template": template,
            "variables": variables,
            "created_by": "_migration_seed",
        }
        for scene, version, prompt_id, template, variables in _SCENES
    ])


def downgrade() -> None:
    scenes = "','".join(scene for scene, *_ in _SCENES)
    op.execute(
        f"DELETE FROM skill_prompt_versions WHERE skill_id IN ('{scenes}')"
    )
    op.execute(f"DELETE FROM skill_prompts WHERE skill_id IN ('{scenes}')")
    op.execute(f"DELETE FROM ai_scene_routes WHERE scene IN ('{scenes}')")
