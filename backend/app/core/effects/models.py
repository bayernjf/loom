"""段13 反馈回流：效果时序记录 effect_records 物理模型（Q126，Q60 契约）。

POST /api/effect-callback（全链唯一反向边数据入口，05 §1.1.1 / 11 §2.1）落库表。

口径：
- 幂等键 (external_content_id, captured_at)：同 content_id + 采集点幂等覆盖，
  同 content_id 不同 captured_at 追加为时间序列（docs/10 行20/394）。
- external_content_id 为推送方自报的本系统内容 ID（原值留存）；命中本系统
  content_products 才回填 matched_content_id（nullable FK）与 tenant_id，
  对不上即 orphan 进孤儿队列（Q60a 人工认领随下一片）。
- metrics 七键稀疏 JSON 存储：缺席键不落、绝不写 0、不许估算（数据纪律硬性）。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType

# 匹配状态：命中本系统成品 / 孤儿（待人工认领，Q60a）。
STATUS_MATCHED = "matched"
STATUS_ORPHAN = "orphan"
STATUSES = (STATUS_MATCHED, STATUS_ORPHAN)

# metrics 七键（05 §1.1.1）：六个非负整数计数 + read_rate 比率（0..1）。
METRIC_COUNTERS = (
    "plays",
    "likes",
    "comments",
    "shares",
    "inquiries",
    "conversions",
)
METRIC_RATE_KEYS = ("read_rate",)
METRIC_KEYS = (*METRIC_COUNTERS, *METRIC_RATE_KEYS)

# source 取值：Agent 标识自由字符串；客户回填固定为该值（Q60）。
CUSTOMER_BACKFILL_SOURCE = "customer-backfill"


def _uuid_pk() -> str:
    return str(uuid.uuid1())


class EffectRecord(Base):
    """外部 Agent 推送的一条效果时序记录。"""

    __tablename__ = "effect_records"
    __table_args__ = (
        # Q60 幂等键：同 content_id + captured_at 幂等覆盖（不新增行）。
        Index(
            "uq_effect_content_captured",
            "external_content_id",
            "captured_at",
            unique=True,
        ),
        Index("ix_effect_records_status", "status"),
        # 某成品的效果时间序列读取（captured_at 升序）。
        Index("ix_effect_records_matched_series", "matched_content_id", "captured_at"),
    )

    record_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_pk)
    # Agent 标识；客户回填时为 "customer-backfill"。
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    # 推送方自报的本系统内容 ID（幂等键组成，原值留存；对不上即为孤儿）。
    external_content_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 命中本系统 content_products 后回填（nullable FK）；孤儿为空，Q60a 认领后补。
    # 单列查询由复合索引 ix_effect_records_matched_series 前缀覆盖，不另建单列索引。
    matched_content_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("content_products.content_id"),
        nullable=True,
    )
    # matched 时由 content.tenant_id 解析回填（Q88：Key 不绑租户，租户由 content 解析）。
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # 平台帖子链接/ID（可能是长 URL，用 Text；不参与自动匹配，仅留存核对）。
    platform_post_id: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # 七键稀疏子集；整组未采集为 NULL；缺席键不存在、绝不写 0。
    metrics: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    # 索引由 __table_args__ 的 ix_effect_records_status 显式提供，不另加 index=True。
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_ORPHAN
    )
    # 验签命中的 Agent Key ID（审计/溯源）。
    received_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
