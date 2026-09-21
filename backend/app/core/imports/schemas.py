"""Q161 客户效果批量回填异步导入任务 Pydantic 契约。

与 Q156/Q160 同步上传端点同一业务契约（固定 9 列、逐行校验、整批 all-or-nothing、
绝不孤儿），只是把输入包成一个可轮询的任务：CSV 携原文（csv 字段），Excel .xlsx
携标准 base64（content_base64 字段），由 format 决定取哪一个。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.actor import Actor


class BackfillImportJobIn(BaseModel):
    """POST /api/effects/backfill/jobs 请求体（客户通道，actor 留痕、无 Agent Key）。"""

    tenant_id: str = Field(min_length=1)
    content_id: str = Field(min_length=1)
    format: Literal["csv", "xlsx"] = "csv"
    # format=csv 时必填：CSV 原文。
    csv: str | None = None
    # format=xlsx 时必填：.xlsx 字节的标准 base64。
    content_base64: str | None = None
    filename: str | None = None
    actor: Actor

    @model_validator(mode="after")
    def _carrier_payload_present(self) -> "BackfillImportJobIn":
        if self.format == "csv" and not (self.csv or "").strip():
            raise ValueError("csv is required when format is csv")
        if self.format == "xlsx" and not (self.content_base64 or "").strip():
            raise ValueError("content_base64 is required when format is xlsx")
        return self


class BackfillImportJobView(BaseModel):
    """导入任务视图：载体、状态、回执计数与（失败时的）逐行错误。"""

    job_id: str
    tenant_id: str
    content_id: str
    format: str
    filename: str | None
    status: str
    received: int
    matched: int
    orphan: int
    upserted: int
    row_count: int
    requested_by: str
    error: str | None
    errors: list[dict] | None
    created_at: datetime
    completed_at: datetime | None


class BackfillImportJobList(BaseModel):
    """GET 列表（按租户、可选成品过滤，新建在前）。"""

    tenant_id: str
    count: int
    jobs: list[BackfillImportJobView]
