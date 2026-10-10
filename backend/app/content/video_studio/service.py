"""段12 视频分段编目＋原片留档服务（Q336）。

①甲 分段实体：人工编辑只改分段元数据（seq/start_ms/end_ms/type/source_leaf），
不动 content.body（不触发重生成）；改 text 不直接生效——返回 needs_regen 标记，
由调用方走既有 generate/regenerate 链路重生成。编辑后由路由层重跑屏4 CCR 复检。
③甲 原片留档：登记 MinIO 对象（bucket/object_key/size/source），管理端经后端
代理只读流访问；本模块只写登记表＋审计，S3 读写由 router 层 boto3 执行（便于
无 S3 环境的测试用登记表口径单测）。
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.video_studio.models import (
    OBJECT_SOURCES,
    SEGMENT_TYPES,
    VideoObject,
    VideoSegment,
)
from app.core.audit import append_audit


class SegmentNotFound(Exception):
    pass


class ObjectNotFound(Exception):
    pass


class InvalidSegmentType(Exception):
    pass


class InvalidObjectSource(Exception):
    pass


class ContentMissing(Exception):
    pass


async def get_segment(session: AsyncSession, segment_id: str) -> VideoSegment:
    segment = await session.get(VideoSegment, segment_id)
    if segment is None:
        raise SegmentNotFound(segment_id)
    return segment


def _now() -> datetime:
    return datetime.now(UTC)


# ---------- 分段编目（①甲） ----------


async def list_segments(session: AsyncSession, content_id: str) -> list[VideoSegment]:
    return list(
        (
            await session.scalars(
                select(VideoSegment)
                .where(VideoSegment.content_id == content_id)
                .order_by(VideoSegment.seq, VideoSegment.segment_id)
            )
        ).all()
    )


async def create_segment(
    session: AsyncSession,
    *,
    content_id: str,
    tenant_id: str,
    seq: int | None,
    start_ms: int | None,
    end_ms: int | None,
    type: str,
    source_leaf: str | None,
    text: str,
    actor,
) -> VideoSegment:
    if type not in SEGMENT_TYPES:
        raise InvalidSegmentType(
            f"unknown segment type {type!r}; valid: {', '.join(SEGMENT_TYPES)}"
        )
    if not text.strip():
        raise InvalidSegmentType("segment text must not be empty")
    if seq is None:
        current_max = await session.scalar(
            select(func.max(VideoSegment.seq)).where(
                VideoSegment.content_id == content_id
            )
        )
        seq = int(current_max or 0) + 1
    segment = VideoSegment(
        content_id=content_id,
        seq=seq,
        start_ms=start_ms,
        end_ms=end_ms,
        type=type,
        source_leaf=source_leaf,
        text=text,
        created_by=actor.id,
    )
    session.add(segment)
    await session.flush()
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="video_segment.create",
        entity_type="video_segment",
        entity_id=segment.segment_id,
        detail={"content_id": content_id, "seq": seq, "type": type},
    )
    return segment


async def update_segment(
    session: AsyncSession,
    segment_id: str,
    *,
    tenant_id: str,
    seq: int | None,
    start_ms: int | None,
    end_ms: int | None,
    type: str | None,
    source_leaf: str | None,
    text: str | None,
    actor,
) -> tuple[VideoSegment, bool]:
    """编辑分段。返回 (segment, needs_regen)：改 text 不直接生效重生成，
    只落新文本并标 needs_regen=True，由调用方决定是否走既有重生成链路。"""
    segment = await session.get(VideoSegment, segment_id)
    if segment is None:
        raise SegmentNotFound(segment_id)
    if type is not None and type not in SEGMENT_TYPES:
        raise InvalidSegmentType(
            f"unknown segment type {type!r}; valid: {', '.join(SEGMENT_TYPES)}"
        )
    changed: dict = {}
    if seq is not None and seq != segment.seq:
        changed["seq"] = {"from": segment.seq, "to": seq}
        segment.seq = seq
    if start_ms is not None and start_ms != segment.start_ms:
        changed["start_ms"] = {"from": segment.start_ms, "to": start_ms}
        segment.start_ms = start_ms
    if end_ms is not None and end_ms != segment.end_ms:
        changed["end_ms"] = {"from": segment.end_ms, "to": end_ms}
        segment.end_ms = end_ms
    if type is not None and type != segment.type:
        changed["type"] = {"from": segment.type, "to": type}
        segment.type = type
    if source_leaf is not None and source_leaf != segment.source_leaf:
        changed["source_leaf"] = {"from": segment.source_leaf, "to": source_leaf}
        segment.source_leaf = source_leaf
    needs_regen = False
    if text is not None and text.strip() and text != segment.text:
        changed["text"] = {"from_len": len(segment.text), "to_len": len(text)}
        segment.text = text
        needs_regen = True
    segment.updated_by = actor.id
    segment.updated_at = _now()
    await session.flush()
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="video_segment.update",
        entity_type="video_segment",
        entity_id=segment_id,
        detail={"content_id": segment.content_id, "changed": changed,
                "needs_regen": needs_regen},
    )
    return segment, needs_regen


# ---------- 原片留档（③甲） ----------


async def list_objects(session: AsyncSession, content_id: str) -> list[VideoObject]:
    return list(
        (
            await session.scalars(
                select(VideoObject)
                .where(VideoObject.content_id == content_id)
                .order_by(VideoObject.created_at, VideoObject.object_id)
            )
        ).all()
    )


async def register_object(
    session: AsyncSession,
    *,
    content_id: str,
    tenant_id: str,
    bucket: str,
    object_key: str,
    size_bytes: int | None,
    content_type: str | None,
    source: str,
    actor,
) -> VideoObject:
    if source not in OBJECT_SOURCES:
        raise InvalidObjectSource(
            f"unknown object source {source!r}; valid: {', '.join(OBJECT_SOURCES)}"
        )
    obj = VideoObject(
        content_id=content_id,
        bucket=bucket,
        object_key=object_key,
        size_bytes=size_bytes,
        content_type=content_type,
        source=source,
        created_by=actor.id,
    )
    session.add(obj)
    await session.flush()
    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="video_object.register",
        entity_type="video_object",
        entity_id=obj.object_id,
        detail={
            "content_id": content_id,
            "bucket": bucket,
            "object_key": object_key,
            "size_bytes": size_bytes,
            "source": source,
        },
    )
    return obj


async def get_object(session: AsyncSession, object_id: str) -> VideoObject:
    obj = await session.get(VideoObject, object_id)
    if obj is None:
        raise ObjectNotFound(object_id)
    return obj
