"""Q161 客户效果批量回填异步导入任务 ORM（镜像 Q137 export_jobs）。

与导出的关键差异：导入是写操作且必须能在后台重放，故 **payload 原样落库**
（CSV 原文，或 Excel .xlsx 的标准 base64），不像导出那样可在下载时按参数重渲染。
状态用 String(16)（不引入 DB 枚举，零迁移加态），默认 completed 保持 V1
「worker 门控关闭＝请求内同步完成」的单副本行为。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_TERMINAL_STATES = frozenset({JOB_COMPLETED, JOB_FAILED})


def new_job_id() -> str:
    return str(uuid.uuid1())


class ImportJob(Base):
    """一次客户效果批量回填导入任务（CSV 或 Excel .xlsx）。"""

    __tablename__ = "import_jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    content_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 载体：csv | xlsx。
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    # 异步重放所需的输入原文：csv＝CSV 文本；xlsx＝.xlsx 字节的标准 base64。
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=JOB_COMPLETED
    )
    # 回执计数（同 CustomerBackfillUploadReceipt；orphan 恒 0）。
    received: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    matched: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    orphan: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    upserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    requested_by: Mapped[str] = mapped_column(String(64), nullable=False)
    # 失败摘要（基础设施异常 / 校验失败总消息）。
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 确定性业务校验失败的逐行错误（JSON 文本，截断前 N 条）；成功为 NULL。
    errors: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
