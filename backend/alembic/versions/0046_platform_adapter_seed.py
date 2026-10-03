"""V1 engine prep slice: seed ai_scene_routes PLATFORM-ADAPTER -> synthetic model
and PLATFORM-ADAPTER prompt v0.1 (PT-PLATFORM-ADAPTER-V1.0). Data-only migration,
no schema change. Q260.

Revision ID: 0046_platform_adapter_seed
Revises: 0045_platform_dynamic_signal
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.model_registry.seeds import (
    PLATFORM_ADAPTER_PROMPT_ID,
    PLATFORM_ADAPTER_PROMPT_TEMPLATE,
    PLATFORM_ADAPTER_PROMPT_VARIABLES,
    PLATFORM_ADAPTER_PROMPT_VERSION,
    SCENE_PLATFORM_ADAPTER,
    SYNTHETIC_MODEL_ID,
)

revision: str = "0046_platform_adapter_seed"
down_revision: str | None = "0045_platform_dynamic_signal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ai_scene_routes = sa.table(
        "ai_scene_routes",
        sa.column("scene", sa.String), sa.column("model_id", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(ai_scene_routes, [{
        "scene": SCENE_PLATFORM_ADAPTER, "model_id": SYNTHETIC_MODEL_ID,
        "updated_by": "_migration_seed",
    }])

    skill_prompts = sa.table(
        "skill_prompts",
        sa.column("skill_id", sa.String), sa.column("current_version", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(skill_prompts, [{
        "skill_id": SCENE_PLATFORM_ADAPTER, "current_version": PLATFORM_ADAPTER_PROMPT_VERSION,
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
        "version_id": PLATFORM_ADAPTER_PROMPT_ID,
        "skill_id": SCENE_PLATFORM_ADAPTER,
        "version": PLATFORM_ADAPTER_PROMPT_VERSION,
        "template": PLATFORM_ADAPTER_PROMPT_TEMPLATE,
        "variables": PLATFORM_ADAPTER_PROMPT_VARIABLES,
        "created_by": "_migration_seed",
    }])


def downgrade() -> None:
    op.execute(
        f"DELETE FROM skill_prompt_versions WHERE skill_id = '{SCENE_PLATFORM_ADAPTER}'"
    )
    op.execute(f"DELETE FROM skill_prompts WHERE skill_id = '{SCENE_PLATFORM_ADAPTER}'")
    op.execute(f"DELETE FROM ai_scene_routes WHERE scene = '{SCENE_PLATFORM_ADAPTER}'")
