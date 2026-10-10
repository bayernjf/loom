"""段12 视频分段编目＋原片对象登记（Q336，design-segment12-video-candidates §3-①甲/③甲）。

video_segments：分段实体（①甲 句子粒度；start_ms/end_ms 可空——无供应商时间戳时
纯文本序）。人工编辑只改分段元数据，不动 content.body（不触发重生成）；改文本
走既有生成链路重生成，编辑后由路由层重跑屏4 CCR 复检（advisory）。
video_objects：原片留档登记（③甲 MinIO 只存原片）；对象本体在 S3 兼容存储，
本表只登记 key/大小/来源；管理端经后端代理只读流访问，不暴露直连。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SEGMENT_TYPES = ("hook", "intro", "body", "climax", "ending", "cta")
OBJECT_SOURCES = ("upload", "agnes", "transcode")


def _uuid() -> str:
    return str(uuid.uuid1())


class VideoSegment(Base):
    __tablename__ = "video_segments"

    segment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    content_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="body")
    source_leaf: Mapped[str | None] = mapped_column(String(128), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class VideoObject(Base):
    __tablename__ = "video_objects"

    object_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    content_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="upload")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
