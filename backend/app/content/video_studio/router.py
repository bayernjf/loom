"""video-studio 段12 分段编目＋原片留档端点（Q336）。

读口（list）＝operations/platform_admin query actor（同 Q326 管理端跨租户只读口径）；
写口（create/update/register/upload）＝operations 硬闸 require_internal_actor
（进 test_write_gate_wiring GATED）；全审计。代理流 GET 不暴露 MinIO 直连，
经后端 boto3 拉取转发（③甲）；S3 未配置（LOOM_S3_ENDPOINT_URL 空）时上传/下载
回 503、登记表口径仍可单测。
"""

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import service as content_service
from app.content.video_studio import service
from app.core.actor import Actor
from app.core.config import get_settings
from app.core.db import get_session
from app.core.rbac import OPERATIONS, PLATFORM_ADMIN, PermissionDenied, require_any_role
from app.core.staff_auth.deps import require_internal_actor

router = APIRouter(tags=["video-studio"])


def _read_actor(
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
) -> Actor:
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, OPERATIONS, PLATFORM_ADMIN)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


def _s3_client():
    settings = get_settings()
    if not settings.s3_endpoint_url:
        raise HTTPException(status_code=503, detail="object storage not configured")
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def _segment_view(s: service.VideoSegment) -> dict:
    return {
        "segment_id": s.segment_id,
        "content_id": s.content_id,
        "seq": s.seq,
        "start_ms": s.start_ms,
        "end_ms": s.end_ms,
        "type": s.type,
        "source_leaf": s.source_leaf,
        "text": s.text,
        "created_by": s.created_by,
        "created_at": s.created_at,
        "updated_by": s.updated_by,
        "updated_at": s.updated_at,
    }


def _object_view(o: service.VideoObject) -> dict:
    return {
        "object_id": o.object_id,
        "content_id": o.content_id,
        "bucket": o.bucket,
        "object_key": o.object_key,
        "size_bytes": o.size_bytes,
        "content_type": o.content_type,
        "source": o.source,
        "created_by": o.created_by,
        "created_at": o.created_at,
    }


async def _require_content(session: AsyncSession, content_id: str):
    try:
        return await content_service.get_content(session, content_id)
    except content_service.ContentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------- 分段编目（①甲） ----------


class SegmentCreateRequest(BaseModel):
    seq: int | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    type: str = "body"
    source_leaf: str | None = None
    text: str
    actor: Actor


class SegmentUpdateRequest(BaseModel):
    seq: int | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    type: str | None = None
    source_leaf: str | None = None
    text: str | None = None
    actor: Actor


@router.get("/api/admin/content/{content_id}/video-segments")
async def list_video_segments(
    content_id: str,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(_read_actor),
) -> list[dict]:
    await _require_content(session, content_id)
    rows = await service.list_segments(session, content_id)
    return [_segment_view(row) for row in rows]


@router.post("/api/admin/content/{content_id}/video-segments", status_code=201)
async def create_video_segment(
    content_id: str,
    body: SegmentCreateRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_internal_actor(OPERATIONS)),
) -> dict:
    content = await _require_content(session, content_id)
    try:
        segment = await service.create_segment(
            session,
            content_id=content_id,
            tenant_id=content.tenant_id,
            seq=body.seq,
            start_ms=body.start_ms,
            end_ms=body.end_ms,
            type=body.type,
            source_leaf=body.source_leaf,
            text=body.text,
            actor=actor,
        )
    except service.InvalidSegmentType as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return _segment_view(segment)


@router.put("/api/admin/video-segments/{segment_id}")
async def update_video_segment(
    segment_id: str,
    body: SegmentUpdateRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_internal_actor(OPERATIONS)),
) -> dict:
    try:
        existing = await service.get_segment(session, segment_id)
        content = await content_service.get_content(session, existing.content_id)
        segment, needs_regen = await service.update_segment(
            session,
            segment_id,
            tenant_id=content.tenant_id,
            seq=body.seq,
            start_ms=body.start_ms,
            end_ms=body.end_ms,
            type=body.type,
            source_leaf=body.source_leaf,
            text=body.text,
            actor=actor,
        )
    except service.SegmentNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except content_service.ContentNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidSegmentType as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # ①甲：编辑后重跑屏4 CCR 复检（advisory，不写报告不改文本）。
    recheck = await content_service.script_recheck(session, segment.content_id)
    await session.commit()
    return {**_segment_view(segment), "needs_regen": needs_regen, "script_recheck": recheck}


# ---------- 原片留档（③甲） ----------


@router.get("/api/admin/content/{content_id}/video-objects")
async def list_video_objects(
    content_id: str,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(_read_actor),
) -> list[dict]:
    await _require_content(session, content_id)
    rows = await service.list_objects(session, content_id)
    return [_object_view(row) for row in rows]


@router.post("/api/admin/content/{content_id}/video-objects", status_code=201)
async def upload_video_object(
    content_id: str,
    request: Request,
    filename: str = Query(default="video.bin"),
    actor_id: str = Query(...),
    roles: list[str] = Query(default_factory=list),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """上传原片（原始字节流，免 python-multipart 依赖）：body=文件字节，
    filename 经 query 传入，Content-Type 头即对象 content_type。"""
    actor = Actor(id=actor_id, roles=roles)
    try:
        require_any_role(actor, OPERATIONS)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    content = await _require_content(session, content_id)
    settings = get_settings()
    client = _s3_client()
    data = await request.body()
    if not data:
        raise HTTPException(status_code=422, detail="empty upload body")
    content_type = request.headers.get("content-type", "application/octet-stream")
    object_key = f"originals/{content_id}/{filename}"
    try:
        client.put_object(
            Bucket=settings.s3_bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=502, detail=f"object storage error: {exc}") from exc
    obj = await service.register_object(
        session,
        content_id=content_id,
        tenant_id=content.tenant_id,
        bucket=settings.s3_bucket,
        object_key=object_key,
        size_bytes=len(data),
        content_type=content_type,
        source="upload",
        actor=actor,
    )
    await session.commit()
    return _object_view(obj)


@router.get("/api/admin/video-objects/{object_id}/stream")
async def stream_video_object(
    object_id: str,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(_read_actor),
) -> StreamingResponse:
    try:
        obj = await service.get_object(session, object_id)
    except service.ObjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    client = _s3_client()
    try:
        resp = client.get_object(Bucket=obj.bucket, Key=obj.object_key)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=502, detail=f"object storage error: {exc}") from exc
    return StreamingResponse(
        resp["Body"].iter_chunks(),
        media_type=obj.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{obj.object_key.rsplit("/", 1)[-1]}"'},
    )
