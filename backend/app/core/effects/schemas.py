"""段13 效果回流（effect-callback）Pydantic 契约（Q126–Q129，05 §1.1.1 / 11 §2.1）。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.actor import Actor


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


class CustomerEffectBatchIn(BaseModel):
    """Q128 客户回填通道 POST /api/effects/backfill 请求体。

    source 不接受客户端传入（服务端固定 customer-backfill）；客户只能为本
    tenant_id 下的成品回填，对不上即整批 422（客户通道绝不产生孤儿）。
    """

    tenant_id: str = Field(min_length=1)
    records: list[EffectRecordIn] = Field(min_length=1)
    actor: Actor


class EffectBatchReceipt(BaseModel):
    """整批接收回执，便于推送方核对落库结果（整批 all-or-nothing）。"""

    received: int
    matched: int
    orphan: int
    upserted: int


class CustomerBackfillUploadIn(BaseModel):
    """Q156 客户批量 CSV 服务端上传（整份挂同一成品，零 multipart 依赖）。

    csv 为原始 CSV 文本，表头固定 9 列（同 Q136 前端岛）；服务端解析、逐行
    校验，全合法才整批落库（守 Q128 all-or-nothing、绝不产生孤儿）。
    """

    tenant_id: str = Field(min_length=1)
    content_id: str = Field(min_length=1)
    csv: str = Field(min_length=1)
    filename: str | None = None
    actor: Actor


class BackfillUploadRow(BaseModel):
    """逐行回执中的一行（index＝数据行 0 基、line＝含表头物理行号）。"""

    index: int
    line: int
    platform_post_id: str
    captured_at: datetime


class CustomerBackfillUploadReceipt(EffectBatchReceipt):
    """Q156 上传回执：整批计数 + 逐行 accepted 明细（orphan 恒 0）。"""

    filename: str | None = None
    rows: list[BackfillUploadRow] = []


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
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None


class EffectClaimRequest(BaseModel):
    """Q127/Q60a 运营把一条孤儿记录人工绑定到本系统成品（写口 actor 在体）。"""

    record_id: str = Field(min_length=1)
    content_id: str = Field(min_length=1)
    actor: Actor


class EffectClaimView(BaseModel):
    """认领结果视图：映射本体 + 本次回填的历史记录行数。"""

    external_content_id: str
    content_id: str
    claimed_by: str
    claimed_at: datetime
    updated_rows: int


class EffectClaimItem(BaseModel):
    """Q129 批量认领中的单条：孤儿记录 → 目标成品。"""

    record_id: str = Field(min_length=1)
    content_id: str = Field(min_length=1)


class EffectClaimBatchRequest(BaseModel):
    """Q129 批量认领请求体（整批 all-or-nothing；actor 在体，operations 闸）。"""

    items: list[EffectClaimItem] = Field(min_length=1)
    actor: Actor


class EffectClaimBatchView(BaseModel):
    """批量认领回执：条数与累计回填行数。"""

    claimed: int
    updated_rows: int


class EffectUnclaimRequest(BaseModel):
    """Q129 取消认领/解绑请求体（按推送方自报 ID 删映射；actor 在体）。"""

    external_content_id: str = Field(min_length=1)
    actor: Actor


class EffectUnclaimView(BaseModel):
    """解绑回执：被删映射的外部 ID 与回滚为 orphan 的历史行数。"""

    external_content_id: str
    reverted_rows: int
