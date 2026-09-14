"""Q67/Q82 model gateway: ai_models/ai_model_keys/ai_scene_routes/skill_prompts/
skill_prompt_versions + skill_runs cost columns; synthetic model seed and CAT-RECOG
route + prompt v0.1.

Revision ID: 0014_model_gateway
Revises: 0013_skill7_intake_anchor
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.model_registry.seeds import (
    CAT_RECOG_PROMPT_ID,
    CAT_RECOG_PROMPT_TEMPLATE,
    CAT_RECOG_PROMPT_VARIABLES,
    CAT_RECOG_PROMPT_VERSION,
    SCENE_CAT_RECOG,
    SYNTHETIC_MODEL_CODE,
    SYNTHETIC_MODEL_ID,
    SYNTHETIC_PROVIDER,
)

revision: str = "0014_model_gateway"
down_revision: str | None = "0013_skill7_intake_anchor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_models",
        sa.Column("model_id", sa.String(length=36), primary_key=True),
        sa.Column("model_code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("input_price_per_1m", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("output_price_per_1m", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("currency_code", sa.String(length=3), nullable=True),
        sa.Column("daily_budget", sa.Numeric(12, 4), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("fallback_model_id", sa.String(length=36), sa.ForeignKey("ai_models.model_id"), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "ai_model_keys",
        sa.Column("key_id", sa.String(length=36), primary_key=True),
        sa.Column("model_id", sa.String(length=36), sa.ForeignKey("ai_models.model_id"), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("fingerprint", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_by", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ai_model_keys_model_id", "ai_model_keys", ["model_id"])
    op.create_table(
        "ai_scene_routes",
        sa.Column("scene", sa.String(length=64), primary_key=True),
        sa.Column("model_id", sa.String(length=36), sa.ForeignKey("ai_models.model_id"), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "skill_prompts",
        sa.Column("skill_id", sa.String(length=64), primary_key=True),
        sa.Column("current_version", sa.String(length=16), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "skill_prompt_versions",
        sa.Column("version_id", sa.String(length=36), primary_key=True),
        sa.Column("skill_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=16), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column(
            "variables", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_prompt_version"),
    )
    op.create_index("ix_skill_prompt_versions_skill_id", "skill_prompt_versions", ["skill_id"])

    op.add_column("skill_runs", sa.Column("model_id", sa.String(length=36), nullable=True))
    op.create_index("ix_skill_runs_model_id", "skill_runs", ["model_id"])
    op.add_column("skill_runs", sa.Column("input_cost", sa.Numeric(12, 6), nullable=True))
    op.add_column("skill_runs", sa.Column("output_cost", sa.Numeric(12, 6), nullable=True))
    op.add_column("skill_runs", sa.Column("currency_code", sa.String(length=3), nullable=True))

    ai_models = sa.table(
        "ai_models",
        sa.column("model_id", sa.String), sa.column("model_code", sa.String),
        sa.column("provider", sa.String), sa.column("status", sa.String),
    )
    op.bulk_insert(ai_models, [{
        "model_id": SYNTHETIC_MODEL_ID,
        "model_code": SYNTHETIC_MODEL_CODE,
        "provider": SYNTHETIC_PROVIDER,
        "status": "active",
    }])
    ai_scene_routes = sa.table(
        "ai_scene_routes",
        sa.column("scene", sa.String), sa.column("model_id", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(ai_scene_routes, [{
        "scene": SCENE_CAT_RECOG, "model_id": SYNTHETIC_MODEL_ID,
        "updated_by": "_migration_seed",
    }])
    skill_prompts = sa.table(
        "skill_prompts",
        sa.column("skill_id", sa.String), sa.column("current_version", sa.String),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(skill_prompts, [{
        "skill_id": SCENE_CAT_RECOG, "current_version": CAT_RECOG_PROMPT_VERSION,
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
        "version_id": CAT_RECOG_PROMPT_ID,
        "skill_id": SCENE_CAT_RECOG,
        "version": CAT_RECOG_PROMPT_VERSION,
        "template": CAT_RECOG_PROMPT_TEMPLATE,
        "variables": CAT_RECOG_PROMPT_VARIABLES,
        "created_by": "_migration_seed",
    }])


def downgrade() -> None:
    op.drop_column("skill_runs", "currency_code")
    op.drop_column("skill_runs", "output_cost")
    op.drop_column("skill_runs", "input_cost")
    op.drop_index("ix_skill_runs_model_id", table_name="skill_runs")
    op.drop_column("skill_runs", "model_id")
    op.drop_index("ix_skill_prompt_versions_skill_id", table_name="skill_prompt_versions")
    op.drop_table("skill_prompt_versions")
    op.drop_table("skill_prompts")
    op.drop_table("ai_scene_routes")
    op.drop_index("ix_ai_model_keys_model_id", table_name="ai_model_keys")
    op.drop_table("ai_model_keys")
    op.drop_table("ai_models")
