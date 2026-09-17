"""P4 (V2) slice 2: seed ai_scene_routes ARTICLE-GEN -> synthetic model and
ARTICLE-GEN prompt v0.1. Data-only migration, no schema change.

Revision ID: 0026_article_gen_seed
Revises: 0025_content_products
Create Date: 2026-09-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.model_registry.seeds import (
    ARTICLE_GEN_PROMPT_ID,
    ARTICLE_GEN_PROMPT_TEMPLATE,
    ARTICLE_GEN_PROMPT_VARIABLES,
    ARTICLE_GEN_PROMPT_VERSION,
    SCENE_ARTICLE_GEN,
    SYNTHETIC_MODEL_ID,
)

revision: str = "0026_article_gen_seed"
down_revision: str | None = "0025_content_products"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ai_scene_routes = sa.table(
        "ai_scene_routes",
        sa.column("scene", sa.String), sa.column("model_id", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(ai_scene_routes, [{
        "scene": SCENE_ARTICLE_GEN, "model_id": SYNTHETIC_MODEL_ID,
        "updated_by": "_migration_seed",
    }])

    skill_prompts = sa.table(
        "skill_prompts",
        sa.column("skill_id", sa.String), sa.column("current_version", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(skill_prompts, [{
        "skill_id": SCENE_ARTICLE_GEN, "current_version": ARTICLE_GEN_PROMPT_VERSION,
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
        "version_id": ARTICLE_GEN_PROMPT_ID,
        "skill_id": SCENE_ARTICLE_GEN,
        "version": ARTICLE_GEN_PROMPT_VERSION,
        "template": ARTICLE_GEN_PROMPT_TEMPLATE,
        "variables": ARTICLE_GEN_PROMPT_VARIABLES,
        "created_by": "_migration_seed",
    }])


def downgrade() -> None:
    op.execute(
        f"DELETE FROM skill_prompt_versions WHERE skill_id = '{SCENE_ARTICLE_GEN}'"
    )
    op.execute(f"DELETE FROM skill_prompts WHERE skill_id = '{SCENE_ARTICLE_GEN}'")
    op.execute(f"DELETE FROM ai_scene_routes WHERE scene = '{SCENE_ARTICLE_GEN}'")
