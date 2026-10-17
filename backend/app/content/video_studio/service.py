"""段12 视频分段编目＋原片留档服务（Q336）＋真视频生成任务（Q354）。

①甲 分段实体：人工编辑只改分段元数据（seq/start_ms/end_ms/type/source_leaf），
不动 content.body（不触发重生成）；改 text 不直接生效——返回 needs_regen 标记，
由调用方走既有 generate/regenerate 链路重生成。编辑后由路由层重跑屏4 CCR 复检。
③甲 原片留档：登记 MinIO 对象（bucket/object_key/size/source），管理端经后端
代理只读流访问；本模块只写登记表＋审计，S3 读写由 router 层 boto3 执行（便于
无 S3 环境的测试用登记表口径单测）。
Q354 真视频任务：**登记≠花钱**——`create` 只落一行待审，`approve` 才提交供应商；
提交/轮询一律单次调用不重试，失败置终态并开运营待办（把"要不要再花一次钱"交回人）。
"""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import ContentProduct
from app.content.video_studio.models import (
    OBJECT_SOURCES,
    SEGMENT_TYPES,
    VIDEO_ASPECT_RATIOS,
    VIDEO_MODES,
    VIDEO_SECONDS_MAX,
    VIDEO_SECONDS_MIN,
    VIDEO_SIZES,
    VIDEO_TASK_COMPLETED,
    VIDEO_TASK_FAILED,
    VIDEO_TASK_PENDING,
    VIDEO_TASK_REJECTED,
    VIDEO_TASK_SUBMITTED,
    VIDEO_TASK_TIMED_OUT,
    VideoGenerationTask,
    VideoObject,
    VideoSegment,
)
from app.core.actor import Actor
from app.core.audit import append_audit
from app.core.config import get_settings
from app.core.config_center.knobs import knob
from app.product.modeling.models import OpsTodo


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


# ---------- 真视频生成任务（Q354：异步任务 ＋ 逐单人工 Gate，不自动重试） ----------

VIDEO_GEN_SCENE = "VIDEO-GEN"
TODO_TYPE_VIDEO_TASK = "video_generation_failed"
ENTITY_TYPE_VIDEO_TASK = "video_generation_task"
VIDEO_TASK_TODO_ACTION = "video_task.todo_opened"
VIDEO_CAP_KEY = "content.video_real_daily_seconds_cap"
ROLE_SYSTEM_SWEEP = "system"


class VideoTaskNotFound(Exception):
    pass


class VideoTaskState(Exception):
    """非法状态转换（含"重复 approve/对终态再 sync"）；调用方回 409。"""


class VideoTaskValidation(Exception):
    """入参不符官方契约（mode/seconds/size/aspect_ratio/prompt）；调用方回 422。"""


class VideoTaskGateClosed(Exception):
    """`LOOM_VIDEO_REAL_ENABLED` 关；调用方回 409（零外部调用、零花钱）。"""


class VideoTaskCapReached(Exception):
    """当日已提交秒数超配置中心上限；调用方回 409。"""


class VideoRouteNotReady(Exception):
    """VIDEO-GEN 场景未路由到 active 的 video 能力模型／无 active 密钥；调用方回 409。"""


# router 的 except 元组：四类"该由人处理"的拒绝（404/422 由 _video_task_error 分流）。
VIDEO_TASK_ERRORS = (
    VideoTaskNotFound,
    VideoTaskState,
    VideoTaskValidation,
    VideoTaskGateClosed,
    VideoTaskCapReached,
    VideoRouteNotReady,
)


def _validate_task_params(*, mode: str, seconds: int, size: str, aspect_ratio: str, prompt: str) -> None:
    """逐条按官方接入文档的取值域校验（Q353 取证），越界一律 422 而不是默默改值。"""
    if mode not in VIDEO_MODES:
        raise VideoTaskValidation(f"mode must be one of {', '.join(VIDEO_MODES)}")
    if not isinstance(seconds, int) or isinstance(seconds, bool):
        raise VideoTaskValidation("seconds must be an integer")
    if not VIDEO_SECONDS_MIN <= seconds <= VIDEO_SECONDS_MAX:
        raise VideoTaskValidation(
            f"seconds must be between {VIDEO_SECONDS_MIN} and {VIDEO_SECONDS_MAX}"
        )
    if size not in VIDEO_SIZES:
        raise VideoTaskValidation(f"size must be one of {', '.join(VIDEO_SIZES)}")
    if aspect_ratio not in VIDEO_ASPECT_RATIOS:
        raise VideoTaskValidation(f"aspect_ratio must be one of {', '.join(VIDEO_ASPECT_RATIOS)}")
    if not prompt or not prompt.strip():
        raise VideoTaskValidation("prompt must not be empty")


async def create_video_task(
    session: AsyncSession,
    *,
    content,
    actor: Actor,
    mode: str,
    seconds: int,
    size: str,
    aspect_ratio: str,
    prompt: str,
) -> VideoGenerationTask:
    """登记一次待审的真视频生成请求。**不产生任何外部调用**——花钱发生在 approve。

    门控关时直接 409（V1 现行为＝synthetic 链路一字不变）。路由解析在此做一次，是为了
    让"注册表还没配 video 模型"在创建时就可见，而不是等运营点了 approve 才发现。
    """
    if not get_settings().video_real_enabled:
        raise VideoTaskGateClosed("real video generation is disabled")
    _validate_task_params(mode=mode, seconds=seconds, size=size, aspect_ratio=aspect_ratio, prompt=prompt)
    if not getattr(content, "final_id", ""):
        raise VideoTaskValidation("content has no final_id; issue the FCW before generating video")
    model, _ = await _resolve_route(session)
    task = VideoGenerationTask(
        content_id=content.content_id,
        final_id=content.final_id,
        tenant_id=content.tenant_id,
        provider=model.provider,
        model_code=model.model_code,
        mode=mode,
        prompt=prompt.strip(),
        seconds=seconds,
        size=size,
        aspect_ratio=aspect_ratio,
        status=VIDEO_TASK_PENDING,
        created_by=actor.id,
    )
    session.add(task)
    content_id = content.content_id  # rollback 会 expire 全部实例，错误文案只能提前取纯值
    try:
        await session.flush()
    except IntegrityError as exc:
        # partial unique `uq_video_task_one_open_per_content`：一条成品同时只允许一个
        # 未终结任务。并发双建在这里被 DB 挡下（Q288 同纪律：DB 守卫优先于先查后插）。
        await session.rollback()
        raise VideoTaskState(
            f"content {content_id} already has an open video generation task"
        ) from exc
    await append_audit(
        session,
        tenant_id=content.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="video_task.create",
        entity_type=ENTITY_TYPE_VIDEO_TASK,
        entity_id=task.task_id,
        detail={
            "content_id": task.content_id,
            "final_id": task.final_id,
            "mode": mode,
            "seconds": seconds,
            "size": size,
            "aspect_ratio": aspect_ratio,
            "model_code": task.model_code,
        },
    )
    return task


async def _resolve_route(session: AsyncSession):
    """解析 VIDEO-GEN 真视频路由；注册表没配好一律翻译成 409 领域的异常，不退化成假数据。"""
    from app.core.model_registry import gateway

    try:
        return await gateway.resolve_video_route(session, VIDEO_GEN_SCENE)
    except (gateway.ModelConfigError, gateway.ModelUnavailable) as exc:
        raise VideoRouteNotReady(str(exc)) from exc


async def approve_video_task(session: AsyncSession, task_id: str, actor: Actor) -> VideoGenerationTask:
    """人工 Gate 放行＝真正花钱的那一步。单次提交、失败即终态、不重试（Q354 裁决②）。"""
    task = await _require_open_task(session, task_id, VIDEO_TASK_PENDING)
    if not get_settings().video_real_enabled:
        raise VideoTaskGateClosed("real video generation is disabled")
    await _enforce_daily_cap(session)
    await _submit(session, task, actor)
    return task


async def reject_video_task(
    session: AsyncSession, task_id: str, actor: Actor, reason: str
) -> VideoGenerationTask:
    task = await _require_open_task(session, task_id, VIDEO_TASK_PENDING)
    if not reason or not reason.strip():
        raise VideoTaskValidation("reason is required")
    task.status = VIDEO_TASK_REJECTED
    task.error = reason.strip()[:2000]
    task.updated_at = _now()
    task.finished_at = _now()
    await session.flush()
    await append_audit(
        session,
        tenant_id=task.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="video_task.reject",
        entity_type=ENTITY_TYPE_VIDEO_TASK,
        entity_id=task.task_id,
        detail={"content_id": task.content_id, "reason": task.error},
    )
    return task


async def sync_video_task(session: AsyncSession, task_id: str, actor: Actor) -> VideoGenerationTask:
    """查一次外部状态（运营手动刷，或被 sweep 作业调用）。轮询不花钱，但仍出网＝门控管住。"""
    task = await _require_open_task(session, task_id, VIDEO_TASK_SUBMITTED)
    if not get_settings().video_real_enabled:
        raise VideoTaskGateClosed("real video generation is disabled")
    return await _sync_one(session, task, actor.roles, by=actor.id)


async def sweep_video_generation_tasks(session: AsyncSession, now: datetime) -> int:
    """第 7 个 sweep 作业（Q354）：轮询到点的 submitted 任务＋置超时。

    与 Q294 同形制（复用既有 300s tick ＋ Q89 leader 锁 ＋ Q151 fence，不新建循环），
    env 门控 `LOOM_VIDEO_REAL_ENABLED` 默认关＝空转返回 0。间隔取
    `settings.video_task_poll_interval_seconds`，超时取 `video_task_timeout_seconds`。
    """
    settings = get_settings()
    if not settings.video_real_enabled:
        return 0
    stmt = select(VideoGenerationTask).where(
        VideoGenerationTask.status == VIDEO_TASK_SUBMITTED
    )
    rows = list(await session.scalars(stmt))
    touched = 0
    for task in rows:
        if _timed_out(task, now, settings.video_task_timeout_seconds):
            await _finalize_failed(
                session,
                task,
                error=f"poll timeout after {settings.video_task_timeout_seconds:.0f}s",
                vendor_status="timed_out",
                actor_roles=[ROLE_SYSTEM_SWEEP],
                by="system:sweep",
            )
            touched += 1
            continue
        if not _poll_due(task, now, settings.video_task_poll_interval_seconds):
            continue
        before = task.status
        await _sync_one(session, task, [ROLE_SYSTEM_SWEEP], by="system:sweep", now=now)
        if task.status != before:
            touched += 1
    return touched


# ---------- 内部件 ----------


async def _require_open_task(session: AsyncSession, task_id: str, expect: str) -> VideoGenerationTask:
    task = await session.get(VideoGenerationTask, task_id)
    if task is None:
        raise VideoTaskNotFound(task_id)
    if task.status != expect:
        raise VideoTaskState(f"task {task_id} is {task.status}, expected {expect}")
    return task


def _timed_out(task: VideoGenerationTask, now: datetime, timeout_seconds: float) -> bool:
    if task.approved_at is None:
        return False
    return (now - _as_utc(task.approved_at)).total_seconds() >= timeout_seconds


def _poll_due(task: VideoGenerationTask, now: datetime, interval_seconds: float) -> bool:
    stamp = task.last_polled_at or task.approved_at
    if stamp is None:
        return True
    return (now - _as_utc(stamp)).total_seconds() >= interval_seconds


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def _daily_submitted_seconds(session: AsyncSession, now: datetime) -> int:
    """当日（UTC 自然日）已提交的秒数＝已花钱与正在花的总量。"""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total = await session.scalar(
        select(func.coalesce(func.sum(VideoGenerationTask.seconds), 0)).where(
            VideoGenerationTask.approved_at >= day_start
        )
    )
    return int(total or 0)


async def _enforce_daily_cap(session: AsyncSession) -> None:
    cap = int(knob(VIDEO_CAP_KEY))
    used = await _daily_submitted_seconds(session, _now())
    if used >= cap:
        raise VideoTaskCapReached(f"daily video seconds cap reached ({used}/{cap}s)")


async def _submit(session: AsyncSession, task: VideoGenerationTask, actor: Actor) -> None:
    from app.core.model_registry import video_drivers

    now = _now()
    try:
        model, api_key = await _resolve_route(session)
    except VideoRouteNotReady as exc:
        await _finalize_failed(
            session, task, error=f"route unresolved: {exc}", vendor_status="route_error",
            actor_roles=actor.roles, by=actor.id, now=now,
        )
        return
    task.provider, task.model_code = model.provider, model.model_code
    try:
        submission = await video_drivers.submit_video_task(
            provider=model.provider,
            model_code=model.model_code,
            api_key=api_key,
            prompt=task.prompt,
            mode=task.mode,
            seconds=task.seconds,
            size=task.size,
            aspect_ratio=task.aspect_ratio,
        )
    except (video_drivers.VideoDriverError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        # 一次都不重试：503 队列满／形状不符／传输错一律置 failed＋开待办，由人决定要不要再发。
        await _finalize_failed(
            session, task, error=str(exc)[:1000], vendor_status="submit_error",
            actor_roles=actor.roles, by=actor.id, now=now,
        )
        return
    task.status = VIDEO_TASK_SUBMITTED
    task.vendor_video_id = submission.video_id
    task.vendor_task_id = submission.task_id
    task.approved_by = actor.id
    task.approved_at = now
    task.last_polled_at = None
    task.error = None
    task.polls = 0
    task.updated_at = now
    await session.flush()
    await append_audit(
        session,
        tenant_id=task.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="video_task.approve",
        entity_type=ENTITY_TYPE_VIDEO_TASK,
        entity_id=task.task_id,
        detail={
            "content_id": task.content_id,
            "vendor_video_id": task.vendor_video_id,
            "seconds": task.seconds,
            "model_code": task.model_code,
        },
    )


async def _sync_one(
    session: AsyncSession,
    task: VideoGenerationTask,
    actor_roles: list[str],
    *,
    by: str,
    now: datetime | None = None,
) -> VideoGenerationTask:
    from app.core.model_registry import video_drivers

    now = now or _now()
    try:
        model, api_key = await _resolve_route(session)
    except VideoRouteNotReady as exc:
        await _finalize_failed(
            session, task, error=f"route unresolved: {exc}", vendor_status="route_error",
            actor_roles=actor_roles, by=by, now=now,
        )
        return task
    try:
        result = await video_drivers.poll_video_task(
            provider=model.provider,
            model_code=model.model_code,
            api_key=api_key,
            video_id=task.vendor_video_id or "",
        )
    except (video_drivers.VideoDriverError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        task.last_polled_at = now
        task.polls += 1
        task.error = str(exc)[:1000]
        task.updated_at = now
        await session.flush()
        return task  # 单次轮询失败不算终态；超时口径负责收口
    task.polls += 1
    task.last_polled_at = now
    if not result.done:
        task.updated_at = now
        await session.flush()
        return task
    if result.succeeded:
        task.status = VIDEO_TASK_COMPLETED
        task.url = result.url
        task.error = None
        task.finished_at = now
        task.updated_at = now
        await session.flush()
        await append_audit(
            session,
            tenant_id=task.tenant_id,
            actor_id=by,
            actor_roles=actor_roles,
            action="video_task.completed",
            entity_type=ENTITY_TYPE_VIDEO_TASK,
            entity_id=task.task_id,
            detail={"content_id": task.content_id, "url": task.url, "polls": task.polls},
        )
        return task
    await _finalize_failed(
        session,
        task,
        error=result.error or f"vendor status {result.vendor_status!r}",
        vendor_status=result.vendor_status,
        actor_roles=actor_roles,
        by=by,
        now=now,
    )
    return task


async def _finalize_failed(
    session: AsyncSession,
    task: VideoGenerationTask,
    *,
    error: str,
    vendor_status: str,
    actor_roles: list[str],
    by: str,
    now: datetime | None = None,
) -> None:
    """置终态＋开运营待办（不自动重试＝把决定权交回人）。"""
    now = now or _now()
    task.status = VIDEO_TASK_TIMED_OUT if vendor_status == "timed_out" else VIDEO_TASK_FAILED
    task.error = error[:1000]
    task.finished_at = now
    task.updated_at = now
    todo = OpsTodo(
        tenant_id=task.tenant_id,
        todo_type=TODO_TYPE_VIDEO_TASK,
        entity_type=ENTITY_TYPE_VIDEO_TASK,
        entity_id=task.task_id,
        assignee_role="operations",
        detail={
            "content_id": task.content_id,
            "final_id": task.final_id,
            "reason": task.error,
            "vendor_status": vendor_status,
            "seconds": task.seconds,
            "next_step": "人工核实供应商侧队列/额度后再新建一次生成任务（系统不自动重投）",
        },
        due_at=now + timedelta(days=1),
    )
    session.add(todo)
    await session.flush()
    await append_audit(
        session,
        tenant_id=task.tenant_id,
        actor_id=by,
        actor_roles=actor_roles,
        action="video_task.failed",
        entity_type=ENTITY_TYPE_VIDEO_TASK,
        entity_id=task.task_id,
        detail={"content_id": task.content_id, "reason": task.error, "status": task.status},
    )
    await append_audit(
        session,
        tenant_id=task.tenant_id,
        actor_id=by,
        actor_roles=actor_roles,
        action=VIDEO_TASK_TODO_ACTION,
        entity_type=ENTITY_TYPE_VIDEO_TASK,
        entity_id=task.task_id,
        detail={"todo_type": TODO_TYPE_VIDEO_TASK, "vendor_status": vendor_status},
    )


async def list_video_tasks(
    session: AsyncSession,
    *,
    content_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[VideoGenerationTask]:
    stmt = select(VideoGenerationTask)
    if content_id:
        stmt = stmt.where(VideoGenerationTask.content_id == content_id)
    if status:
        stmt = stmt.where(VideoGenerationTask.status == status)
    stmt = stmt.order_by(VideoGenerationTask.created_at.desc()).limit(max(1, min(limit, 500)))
    return list(await session.scalars(stmt))


async def get_video_task(session: AsyncSession, task_id: str) -> VideoGenerationTask:
    task = await session.get(VideoGenerationTask, task_id)
    if task is None:
        raise VideoTaskNotFound(task_id)
    return task


async def attach_video_to_content(
    session: AsyncSession, task_id: str, actor: Actor
) -> VideoGenerationTask:
    """Q368：completed 的真视频成片**入库**（Q354 裁决留的"下一片"）。

    把供应商返回的成片 url 回填到 `content_products.body`——body 是成片引用载体
    （synthetic VIDEO-GEN 写的是 video_ref 占位字符串，见 `generation.py:226`），
    入库＝占位引用替换为真实成片 url。人工逐单动作（router 挂 operations 凭证闸）；
    仅 completed 且 url 非空可入（否则 409）；幂等——body 已是同一 url 直接返回。
    改的是成片引用、不改变正文语义，不触发重生成（段12 视频复检规格未给【待补】，
    V1 不跑文本复检，同 `generation.py` docstring 口径）。
    """
    task = await session.get(VideoGenerationTask, task_id)
    if task is None:
        raise VideoTaskNotFound(task_id)
    if task.status != VIDEO_TASK_COMPLETED or not task.url:
        raise VideoTaskState(
            "only a completed task with a url can be attached to content, "
            f"current status={task.status}"
        )
    content = await session.get(ContentProduct, task.content_id)
    if content is None:
        raise VideoTaskState(f"content {task.content_id} not found for attach")
    if content.body != task.url:
        before = content.body
        content.body = task.url
        content.updated_at = _now()
        await append_audit(
            session,
            tenant_id=task.tenant_id,
            actor_id=actor.id,
            actor_roles=actor.roles,
            action="video_task.attached_to_content",
            entity_type=ENTITY_TYPE_VIDEO_TASK,
            entity_id=task.task_id,
            detail={
                "content_id": task.content_id,
                "final_id": task.final_id,
                "before_body": before,
                "url": task.url,
            },
        )
    return task


def video_task_view(task: VideoGenerationTask) -> dict:
    return {
        "task_id": task.task_id,
        "content_id": task.content_id,
        "final_id": task.final_id,
        "tenant_id": task.tenant_id,
        "provider": task.provider,
        "model_code": task.model_code,
        "mode": task.mode,
        "prompt": task.prompt,
        "seconds": task.seconds,
        "size": task.size,
        "aspect_ratio": task.aspect_ratio,
        "status": task.status,
        "vendor_video_id": task.vendor_video_id,
        "vendor_task_id": task.vendor_task_id,
        "url": task.url,
        "error": task.error,
        "polls": task.polls,
        "created_by": task.created_by,
        "created_at": task.created_at,
        "approved_by": task.approved_by,
        "approved_at": task.approved_at,
        "last_polled_at": task.last_polled_at,
        "finished_at": task.finished_at,
    }
