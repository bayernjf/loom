"""Q121 (Q59) P4 slice: seed ai_scene_routes ARTICLE-SEMANTIC-CHECK -> synthetic
model and ARTICLE-SEMANTIC-CHECK prompt v0.1 (re-check item 2, semantic-level).
Data-only migration, no schema change.

Revision ID: 0031_article_semantic_seed
Revises: 0030_article_qc_seed
Create Date: 2026-09-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.model_registry.seeds import (
    ARTICLE_SEMANTIC_PROMPT_ID,
    ARTICLE_SEMANTIC_PROMPT_TEMPLATE,
    ARTICLE_SEMANTIC_PROMPT_VARIABLES,
    ARTICLE_SEMANTIC_PROMPT_VERSION,
    SCENE_ARTICLE_SEMANTIC,
    SYNTHETIC_MODEL_ID,
)

revision: str = "0031_article_semantic_seed"
down_revision: str | None = "0030_article_qc_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ai_scene_routes = sa.table(
        "ai_scene_routes",
        sa.column("scene", sa.String), sa.column("model_id", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(ai_scene_routes, [{
        "scene": SCENE_ARTICLE_SEMANTIC, "model_id": SYNTHETIC_MODEL_ID,
        "updated_by": "_migration_seed",
    }])

    skill_prompts = sa.table(
        "skill_prompts",
        sa.column("skill_id", sa.String), sa.column("current_version", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(skill_prompts, [{
        "skill_id": SCENE_ARTICLE_SEMANTIC,
        "current_version": ARTICLE_SEMANTIC_PROMPT_VERSION,
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
        "version_id": ARTICLE_SEMANTIC_PROMPT_ID,
        "skill_id": SCENE_ARTICLE_SEMANTIC,
        "version": ARTICLE_SEMANTIC_PROMPT_VERSION,
        "template": ARTICLE_SEMANTIC_PROMPT_TEMPLATE,
        "variables": ARTICLE_SEMANTIC_PROMPT_VARIABLES,
        "created_by": "_migration_seed",
    }])


def downgrade() -> None:
    op.execute(
        f"DELETE FROM skill_prompt_versions WHERE skill_id = '{SCENE_ARTICLE_SEMANTIC}'"
    )
    op.execute(f"DELETE FROM skill_prompts WHERE skill_id = '{SCENE_ARTICLE_SEMANTIC}'")
    op.execute(f"DELETE FROM ai_scene_routes WHERE scene = '{SCENE_ARTICLE_SEMANTIC}'")
