"""Q336: segment-12 video segment catalog + original-video object registry.

Tables `video_segments` (①甲: sentence-granularity segments per content;
start_ms/end_ms nullable when no vendor timestamps) and `video_objects`
(③甲: MinIO original-file registry; object bytes live in S3-compatible
storage, this table only records bucket/key/size/source). PG16 round-trip
required per docs/10; docs/05 contract registration follows.

Revision ID: 0056_video_segments_objects
Revises: 0055_billing_price_seed
Create Date: 2026-10-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0056_video_segments_objects"
down_revision: str | None = "0055_billing_price_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_segments",
        sa.Column("segment_id", sa.String(36), primary_key=True),
        sa.Column("content_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(16), nullable=False, server_default="body"),
        sa.Column("source_leaf", sa.String(128), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_video_segments_content_id", "video_segments", ["content_id"])

    op.create_table(
        "video_objects",
        sa.Column("object_id", sa.String(36), primary_key=True),
        sa.Column("content_id", sa.String(36), nullable=False),
        sa.Column("bucket", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(64), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="upload"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_video_objects_content_id", "video_objects", ["content_id"])


def downgrade() -> None:
    op.drop_index("ix_video_objects_content_id", table_name="video_objects")
    op.drop_table("video_objects")
    op.drop_index("ix_video_segments_content_id", table_name="video_segments")
    op.drop_table("video_segments")
