"""Q132 中台导出任务记录（JSON 形态 + 异步导出，V1 同步落表）。

GET /api/exports/fcw.csv（Q100）只提供同步 CSV；Q132 补：
- GET /api/exports/fcw.json 同步 JSON 形态（与 CSV 同口径，只导 published）；
- POST /api/exports/jobs 导出任务记录——门控关闭时在请求内同步生成并置 completed；
  Q137 起门控开启（LOOM_EXPORT_WORKER_ENABLED）走 queued→running→completed/failed
  真后台 worker（Redis Streams 消费组）。下载按任务参数重新查询渲染（不存文件大
  字段、幂等反映当前 published 集合）。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

FORMAT_CSV = "csv"
FORMAT_JSON = "json"
EXPORT_FORMATS = (FORMAT_CSV, FORMAT_JSON)

# V1 同步执行：门控关闭时创建即 completed/failed。
# Q137：门控开启（LOOM_EXPORT_WORKER_ENABLED）走 queued→running→completed/failed
# 真后台 worker（Redis Streams 消费组）。status 为 String(16) 无 DB 枚举，零迁移。
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"

# 异步生命周期终态集合（用于重复投递幂等判断）。
JOB_TERMINAL_STATES = frozenset({JOB_COMPLETED, JOB_FAILED})


def _uuid_pk() -> str:
    return str(uuid.uuid1())  # 时间有序，同秒内仍唯一


class ExportJob(Base):
    """中台导出任务（Q132）：参数与结果留痕，文件内容下载时按参数重渲染。"""

    __tablename__ = "export_jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_pk)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=JOB_COMPLETED
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_name: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
