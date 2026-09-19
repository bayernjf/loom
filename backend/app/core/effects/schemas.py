"""段13 效果回流（effect-callback）Pydantic 契约（Q126，05 §1.1.1 / 11 §2.1）。"""

from datetime import datetime

from pydantic import BaseModel, Field


class EffectRecordIn(BaseModel):
    """单条效果记录；metrics 为稀疏对象，键白名单与类型由服务层纯函数校验。"""

    content_id: str = Field(min_length=1)
    platform_post_id: str = Field(min_length=1)
    captured_at: datetime
    metrics: dict | None = None


class EffectBatchIn(BaseModel):
    """POST /api/effect-callback 请求体；source 必填、records 至少一条。"""

    source: str = Field(min_length=1)
    records: list[EffectRecordIn] = Field(min_length=1)


class EffectBatchReceipt(BaseModel):
    """整批接收回执，便于推送方核对落库结果（整批 all-or-nothing）。"""

    received: int
    matched: int
    orphan: int
    upserted: int


class EffectRecordView(BaseModel):
    """效果记录只读视图（孤儿队列 / 成品时序）。"""

    record_id: str
    source: str
    content_id: str
    matched_content_id: str | None
    tenant_id: str | None
    platform_post_id: str
    captured_at: datetime
    metrics: dict | None
    status: str
    created_at: datetime
    updated_at: datetime | None
