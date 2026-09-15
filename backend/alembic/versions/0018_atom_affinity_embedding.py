"""Q86 WF-03 atom expand (CONFLICT-PRECHECK chat + ATOM-AFFINITY embedding)
real-LLM slice: first schema-bearing LLM migration.

- CREATE EXTENSION vector (pgvector) on PostgreSQL;
- ai_models.capability (chat|embedding, default chat);
- nullable 1536-dim embedding columns on atom_candidates and
  product_atom_instances (copied from candidate on approve);
- atom.cluster_line config seed (0.9, borrowed from Q10 synonym line — source
  text does not specify a cluster line, marked 原文未给);
- second synthetic model (synthetic-embedding, capability=embedding);
- scene routes CONFLICT-PRECHECK -> synthetic chat model and
  ATOM-AFFINITY -> synthetic embedding model;
- CONFLICT-PRECHECK prompt v0.1.

Revision ID: 0018_atom_affinity_embedding
Revises: 0017_dim_merge_seed
Create Date: 2026-09-15

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS
from app.core.model_registry.seeds import (
    CONFLICT_PRECHECK_PROMPT_ID,
    CONFLICT_PRECHECK_PROMPT_TEMPLATE,
    CONFLICT_PRECHECK_PROMPT_VARIABLES,
    CONFLICT_PRECHECK_PROMPT_VERSION,
    SCENE_ATOM_AFFINITY,
    SCENE_CONFLICT_PRECHECK,
    SYNTHETIC_EMBEDDING_MODEL_CODE,
    SYNTHETIC_EMBEDDING_MODEL_ID,
    SYNTHETIC_MODEL_ID,
    SYNTHETIC_PROVIDER,
)

revision: str = "0018_atom_affinity_embedding"
down_revision: str | None = "0017_dim_merge_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1536
_CLUSTER_LINE_SEED = next(row for row in CONFIG_SEEDS if row[0] == "atom.cluster_line")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "ai_models",
        sa.Column(
            "capability",
            sa.String(length=16),
            nullable=False,
            server_default="chat",
        ),
    )

    op.add_column(
        "atom_candidates",
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )
    op.add_column(
        "product_atom_instances",
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )

    # atom.cluster_line 配置种子（同 0010：item + v1 version，确定性 uuid5）。
    # 0010 按当前 CONFIG_SEEDS 快照播种：全新库上行 0010 时该键已存在，
    # 故幂等 ON CONFLICT DO NOTHING（旧库从 0017 升级时由本迁移补行）。
    key, category, value_type, value, source_ref, validation = _CLUSTER_LINE_SEED
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    config_items_t = sa.table(
        "config_items",
        sa.column("key", sa.String),
        sa.column("category", sa.String),
        sa.column("value", json_type),
        sa.column("value_type", sa.String),
        sa.column("validation", json_type),
        sa.column("source_ref", sa.String),
        sa.column("version", sa.Integer),
    )
    config_versions_t = sa.table(
        "config_item_versions",
        sa.column("version_id", sa.String),
        sa.column("key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("value", json_type),
        sa.column("change_note", sa.String),
        sa.column("changed_by", sa.String),
    )
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-config-seed:{key}"))
    bind.execute(
        postgresql.insert(config_items_t).on_conflict_do_nothing(),
        [{
            "key": key,
            "category": category,
            "value": value,
            "value_type": value_type,
            "validation": validation,
            "source_ref": source_ref,
            "version": 1,
        }],
    )
    bind.execute(
        postgresql.insert(config_versions_t).on_conflict_do_nothing(),
        [{
            "version_id": version_id,
            "key": key,
            "version": 1,
            "value": value,
            "change_note": "Q86 seed",
            "changed_by": None,
        }],
    )

    op.bulk_insert(
        sa.table(
            "ai_models",
            sa.column("model_id", sa.String),
            sa.column("model_code", sa.String),
            sa.column("provider", sa.String),
            sa.column("capability", sa.String),
            sa.column("created_by", sa.String),
            sa.column("updated_by", sa.String),
        ),
        [{
            "model_id": SYNTHETIC_EMBEDDING_MODEL_ID,
            "model_code": SYNTHETIC_EMBEDDING_MODEL_CODE,
            "provider": SYNTHETIC_PROVIDER,
            "capability": "embedding",
            "created_by": "_migration_seed",
            "updated_by": "_migration_seed",
        }],
    )

    op.bulk_insert(
        sa.table(
            "ai_scene_routes",
            sa.column("scene", sa.String),
            sa.column("model_id", sa.String),
            sa.column("updated_by", sa.String),
        ),
        [
            {
                "scene": SCENE_CONFLICT_PRECHECK,
                "model_id": SYNTHETIC_MODEL_ID,
                "updated_by": "_migration_seed",
            },
            {
                "scene": SCENE_ATOM_AFFINITY,
                "model_id": SYNTHETIC_EMBEDDING_MODEL_ID,
                "updated_by": "_migration_seed",
            },
        ],
    )

    op.bulk_insert(
        sa.table(
            "skill_prompts",
            sa.column("skill_id", sa.String),
            sa.column("current_version", sa.String),
            sa.column("updated_by", sa.String),
        ),
        [{
            "skill_id": SCENE_CONFLICT_PRECHECK,
            "current_version": CONFLICT_PRECHECK_PROMPT_VERSION,
            "updated_by": "_migration_seed",
        }],
    )
    op.bulk_insert(
        sa.table(
            "skill_prompt_versions",
            sa.column("version_id", sa.String),
            sa.column("skill_id", sa.String),
            sa.column("version", sa.String),
            sa.column("template", sa.Text),
            sa.column("variables", postgresql.JSONB(astext_type=sa.Text())),
            sa.column("created_by", sa.String),
        ),
        [{
            "version_id": CONFLICT_PRECHECK_PROMPT_ID,
            "skill_id": SCENE_CONFLICT_PRECHECK,
            "version": CONFLICT_PRECHECK_PROMPT_VERSION,
            "template": CONFLICT_PRECHECK_PROMPT_TEMPLATE,
            "variables": CONFLICT_PRECHECK_PROMPT_VARIABLES,
            "created_by": "_migration_seed",
        }],
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM skill_prompt_versions WHERE skill_id = '{SCENE_CONFLICT_PRECHECK}'"
    )
    op.execute(f"DELETE FROM skill_prompts WHERE skill_id = '{SCENE_CONFLICT_PRECHECK}'")
    op.execute(
        f"DELETE FROM ai_scene_routes WHERE scene IN "
        f"('{SCENE_CONFLICT_PRECHECK}', '{SCENE_ATOM_AFFINITY}')"
    )
    op.execute(
        f"DELETE FROM ai_models WHERE model_id = '{SYNTHETIC_EMBEDDING_MODEL_ID}'"
    )
    op.execute("DELETE FROM config_item_versions WHERE key = 'atom.cluster_line'")
    op.execute("DELETE FROM config_items WHERE key = 'atom.cluster_line'")

    op.drop_column("product_atom_instances", "embedding")
    op.drop_column("atom_candidates", "embedding")
    op.drop_column("ai_models", "capability")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 0018 之前不存在任何 vector 列/类型依赖；扩展随切片整体回退。
        op.execute("DROP EXTENSION IF EXISTS vector")
