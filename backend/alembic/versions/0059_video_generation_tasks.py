"""Q354: stage-12 real video generation tasks (vendor async job + per-item human Gate).

Creates `video_generation_tasks` -- one row per "should we spend real money generating
this video" decision and its external trail (provider video_id, status, produced url,
error). Submission only happens on an explicit `approve`, so an unapproved row costs
nothing. There is deliberately **no automatic retry edge**: `503 video_queue_full`,
vendor `status:"failed"` and poll timeout all land in a terminal state plus an
operations todo (ruling ② of the three decisions registered as docs/19 list-2 #17).

A partial unique index keeps at most one open task per content item -- double-paying
for the same video is prevented at the database, not only in the service (Q288 rule:
the index must also be declared on the model with BOTH `postgresql_where` and
`sqlite_where`, or docs/10's drift gate goes red).

Also seeds one business knob, `content.video_real_daily_seconds_cap` (default 120s/day
-- the vendor bills per second, and the cap value itself is 原文未给出 ⇒ engineering
proposal, hot-updatable). Its downgrade follows the Q351/Q352 fingerprint rule: the
row is deleted only while it still matches the seed, and the v1 history row created by
0010 on a fresh database is left alone.

Revision ID: 0059_video_generation_tasks
Revises: 0058_fit_learning_window_seed
Create Date: 2026-10-13

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config_center.seeds import CONFIG_SEEDS

revision: str = "0059_video_generation_tasks"
down_revision: str | None = "0058_fit_learning_window_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN_STATUSES_SQL = "status IN ('pending_approval','submitted')"
_SEED_KEY = "content.video_real_daily_seconds_cap"
# 缺键即硬失败（不静默 no-op）：config_center/seeds.py 是唯一事实源，迁移必须与它对账。
_SEED = next(row for row in CONFIG_SEEDS if row[0] == _SEED_KEY)
_SEED_VERSION_NOTE = "Q354 seed"


def _config_items_table():
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    return sa.table(
        "config_items",
        sa.column("key", sa.String),
        sa.column("category", sa.String),
        sa.column("value", json_type),
        sa.column("value_type", sa.String),
        sa.column("validation", json_type),
        sa.column("source_ref", sa.String),
        sa.column("version", sa.Integer),
    )


def _config_versions_table():
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    return sa.table(
        "config_item_versions",
        sa.column("version_id", sa.String),
        sa.column("key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("value", json_type),
        sa.column("change_note", sa.String),
        sa.column("changed_by", sa.String),
    )


def upgrade() -> None:
    op.create_table(
        "video_generation_tasks",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("content_id", sa.String(36), nullable=False),
        sa.Column("final_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_code", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="text"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("size", sa.String(16), nullable=False, server_default="720P"),
        sa.Column("aspect_ratio", sa.String(8), nullable=False, server_default="16:9"),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="pending_approval"
        ),
        sa.Column("vendor_video_id", sa.String(64), nullable=True),
        sa.Column("vendor_task_id", sa.String(64), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("polls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("content_id", "final_id", "tenant_id", "status"):
        op.create_index(
            f"ix_video_generation_tasks_{column}", "video_generation_tasks", [column]
        )
    # 一条成品只允许一个未终结任务（防双花钱）；partial unique，双写条件见模型 __table_args__。
    op.create_index(
        "uq_video_task_one_open_per_content",
        "video_generation_tasks",
        ["content_id"],
        unique=True,
        postgresql_where=sa.text(_OPEN_STATUSES_SQL),
        sqlite_where=sa.text(_OPEN_STATUSES_SQL),
    )

    bind = op.get_bind()
    key, category, value_type, value, source_ref, validation = _SEED
    config_items = _config_items_table()
    config_versions = _config_versions_table()
    bind.execute(
        postgresql.insert(config_items).on_conflict_do_nothing(),
        [
            {
                "key": key,
                "category": category,
                "value": value,
                "value_type": value_type,
                "validation": validation,
                "source_ref": source_ref,
                "version": 1,
            }
        ],
    )
    bind.execute(
        postgresql.insert(config_versions).on_conflict_do_nothing(),
        [
            {
                "version_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-config-seed:{key}")),
                "key": key,
                "version": 1,
                "value": value,
                "change_note": _SEED_VERSION_NOTE,
                "changed_by": None,
            }
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    key, _category, _value_type, value, _source_ref, validation = _SEED
    config_items = _config_items_table()
    config_versions = _config_versions_table()

    # 先比 JSON 指纹（JSONB 没有可用的 SQL 等值算子）再决定删不删：运营改过 value/validation
    # 的行连同版本历史一并保留（0058 同纪律）；版本行只删本迁移自己播的那条 change_note，
    # 全新库上 0010 已按当时 CONFIG_SEEDS 快照播过一遍（change_note「C2 seed」），不动它。
    stored = bind.execute(
        sa.select(config_items.c.value, config_items.c.validation).where(
            config_items.c.key == key
        )
    ).first()
    if stored is not None and (stored[0] != value or stored[1] != validation):
        pass  # 定制行保留
    else:
        if stored is not None:
            bind.execute(
                config_versions.delete()
                .where(config_versions.c.key == key)
                .where(config_versions.c.version == 1)
                .where(config_versions.c.change_note == _SEED_VERSION_NOTE)
            )
            bind.execute(sa.delete(config_items).where(config_items.c.key == key))

    op.drop_index("uq_video_task_one_open_per_content", table_name="video_generation_tasks")
    for name in (
        "ix_video_generation_tasks_status",
        "ix_video_generation_tasks_tenant_id",
        "ix_video_generation_tasks_final_id",
        "ix_video_generation_tasks_content_id",
    ):
        op.drop_index(name, table_name="video_generation_tasks")
    op.drop_table("video_generation_tasks")
