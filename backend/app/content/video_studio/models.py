"""段12 视频分段编目＋原片对象登记（Q336，design-segment12-video-candidates §3-①甲/③甲）。

video_segments：分段实体（①甲 句子粒度；start_ms/end_ms 可空——无供应商时间戳时
纯文本序）。人工编辑只改分段元数据，不动 content.body（不触发重生成）；改文本
走既有生成链路重生成，编辑后由路由层重跑屏4 CCR 复检（advisory）。
video_objects：原片留档登记（③甲 MinIO 只存原片）；对象本体在 S3 兼容存储，
本表只登记 key/大小/来源；管理端经后端代理只读流访问，不暴露直连。
video_generation_tasks：**真视频生成任务（Q354）**——供应商异步任务 ＋ 逐单人工 Gate，
一行记一次"要不要花真钱生成这条视频"的裁决与其外部轨迹（`video_id`/状态/产物 URL/错误）。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SEGMENT_TYPES = ("hook", "intro", "body", "climax", "ending", "cta")
OBJECT_SOURCES = ("upload", "agnes", "transcode")

# ---- Q354 真视频生成任务（供应商异步任务的人工 Gate 载体）----
# 状态机：pending_approval --approve--> submitted --轮询--> completed | failed | timed_out
#                     `--reject--> rejected（未提交即终止）
# 终态 = completed / failed / rejected / timed_out；**没有任何自动重试边**（Q354 裁决②：
# 503 队列满、供应商 failed、轮询超时三种一律不重投，只置终态＋开运营待办）。
VIDEO_TASK_PENDING = "pending_approval"
VIDEO_TASK_SUBMITTED = "submitted"
VIDEO_TASK_COMPLETED = "completed"
VIDEO_TASK_FAILED = "failed"
VIDEO_TASK_TIMED_OUT = "timed_out"
VIDEO_TASK_REJECTED = "rejected"
VIDEO_TASK_STATUSES = (
    VIDEO_TASK_PENDING,
    VIDEO_TASK_SUBMITTED,
    VIDEO_TASK_COMPLETED,
    VIDEO_TASK_FAILED,
    VIDEO_TASK_TIMED_OUT,
    VIDEO_TASK_REJECTED,
)
VIDEO_TASK_TERMINAL = (
    VIDEO_TASK_COMPLETED,
    VIDEO_TASK_FAILED,
    VIDEO_TASK_TIMED_OUT,
    VIDEO_TASK_REJECTED,
)
# 官方接入文档给的三个 mode（互斥字段由 service 校验：keyframe→首尾帧、reference→参考素材）。
VIDEO_MODES = ("text", "keyframe", "reference")
VIDEO_SIZES = ("720P", "1080P", "1K", "2K")
VIDEO_ASPECT_RATIOS = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
VIDEO_SECONDS_MIN, VIDEO_SECONDS_MAX = 4, 12


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


class VideoGenerationTask(Base):
    """Q354：段12 真视频生成任务（供应商异步任务 ＋ 人工 Gate 载体）。

    一行＝一次"要不要花真钱生成这条视频"的裁决与它的外部任务轨迹。**提交（approve）是花
    钱动作，必须由 operations 令牌逐单点**；未 approve 的行不产生任何外部调用。状态机没有
    自动重试边——`503 video_queue_full`／供应商 `failed`／轮询超时三种一律置终态并开运营
    待办（Q354 裁决②）。`url` 只在 completed 后有值，**不回写 `content_products.body`**
    （段12 成片是否入库属下一片：这里只登记产物与轨迹，不伪造"已生成"语义）。
    """

    __tablename__ = "video_generation_tasks"
    __table_args__ = (
        # 一条成品同时只允许一个未终结任务（防双花钱）；partial 条件双写，
        # 否则 docs/10 与漂移门会因模型⇄迁移不一致判红（Q288 同纪律）。
        Index(
            "uq_video_task_one_open_per_content",
            "content_id",
            unique=True,
            postgresql_where=text("status IN ('pending_approval','submitted')"),
            sqlite_where=text("status IN ('pending_approval','submitted')"),
        ),
    )

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    content_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 只读软关联 FCW（与 content_products.final_id 同口径，不设硬 FK）。
    final_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 提交时从模型注册表解析到的 provider／编码（注册表改路由不影响已提交行的可追溯性）。
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_code: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    size: Mapped[str] = mapped_column(String(16), nullable=False, default="720P")
    aspect_ratio: Mapped[str] = mapped_column(String(8), nullable=False, default="16:9")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=VIDEO_TASK_PENDING, index=True
    )
    # 供应商侧两个标识：`video_id` 用于轮询，`id`/`task_id` 留作对账（官方两者都给）。
    vendor_video_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vendor_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    polls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
