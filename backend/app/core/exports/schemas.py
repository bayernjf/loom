"""Q132 中台导出任务 Pydantic 契约（docs/11 §2.3）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.actor import Actor


class ExportJobCreate(BaseModel):
    """POST /api/exports/jobs 请求体（中台面，actor 留痕、无 RBAC 闸，同 Q100）。"""

    tenant_id: str = Field(min_length=1)
    product_space_id: str | None = None
    format: Literal["csv", "json"] = "csv"
    actor: Actor


class ExportJobView(BaseModel):
    """导出任务视图：参数、状态与下载地址（V1 同步，创建即 completed）。"""

    job_id: str
    tenant_id: str
    product_space_id: str | None
    format: str
    status: str
    row_count: int
    file_name: str
    requested_by: str
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    download_url: str
