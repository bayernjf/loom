"""Q132 中台导出任务记录（JSON 形态 + 异步导出，V1 同步落表）。

GET /api/exports/fcw.csv（Q100）只提供同步 CSV；Q132 补：
- GET /api/exports/fcw.json 同步 JSON 形态（与 CSV 同口径，只导 published）；
- POST /api/exports/jobs 导出任务记录——V1 在请求内同步生成并置 completed，
  下载按任务参数重新查询渲染（不存文件大字段、幂等反映当前 published 集合）；
  queued/running 后台 worker 形态留给 V2（Redis Streams，见 V2 基建挂账）。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

FORMAT_CSV = "csv"
FORMAT_JSON = "json"
EXPORT_FORMATS = (FORMAT_CSV, FORMAT_JSON)

# V1 同步执行：创建即 completed/failed；queued/running 预留给 V2 后台 worker。
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"


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
