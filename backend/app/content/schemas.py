"""段12 内容生成 Pydantic 契约（P4，V2）。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.content.models import DEFAULT_LANGUAGE, KIND_ARTICLE
from app.core.actor import Actor


class ContentGenerateRequest(BaseModel):
    """operations 显式触发：指定一条 final_id 生成内容成品。"""

    final_id: str = Field(min_length=1)
    kind: str = KIND_ARTICLE
    language: str = DEFAULT_LANGUAGE
    actor: Actor


class ContentDecisionRequest(BaseModel):
    """客户审阅（approve/reject/revise）请求；reject 必选 reason（Q59）。"""

    reason: str | None = None
    actor: Actor


class ContentBodyPatch(BaseModel):
    """Q56-a/Q122：客户在 revising 态人工编辑正文后提交（重过复检回 review）。"""

    body: str = Field(min_length=1)
    actor: Actor


class ContentDiscardRequest(BaseModel):
    """Q56-b/Q124：运营作废骨架回池（discard），难产原因必填。"""

    reason: str = Field(min_length=1, max_length=500)
    actor: Actor


class ContentProductListItem(BaseModel):
    """客户内容列表项（Q122）：与详情同构但不带 body（正文仅在详情返回）。"""

    content_id: str
    tenant_id: str
    product_space_id: str
    final_id: str
    goal: str
    platform: str
    slot_id: str | None
    country: str | None
    kind: str
    language: str
    review_hits: dict
    status: str
    reject_reason: str | None
    regenerate_count: int
    created_at: datetime | None
    discard_reason: str | None = None
    quality_score: float | None = None
    quality_issues: list | None = None
    quality_threshold: float | None = None
    quality_advisory: bool | None = None


class ContentProductView(BaseModel):
    content_id: str
    tenant_id: str
    product_space_id: str
    final_id: str
    goal: str
    platform: str
    slot_id: str | None
    country: str | None
    kind: str
    language: str
    body: str | None
    review_hits: dict
    status: str
    reject_reason: str | None
    regenerate_count: int
    created_at: datetime | None
    # Q124/Q56-b：运营作废回池的难产原因（仅 discarded 态非空）。
    discard_reason: str | None = None
    # Q120/Q57：AI 质量分（辅助参考，不自动发证/驳回）。threshold 为当前配置阈值，
    # advisory=True 表示分数低于阈值（界面提示「需细看」），分数缺失时二者为 None。
    quality_score: float | None = None
    quality_issues: list | None = None
    quality_threshold: float | None = None
    quality_advisory: bool | None = None

class LanguageUpsertRequest(BaseModel):
    """dictionary_admin 维护语言清单（Q58/Q119）：code=BCP-47，markets=适用国家码（空=全市场）。"""

    code: str = Field(min_length=2, max_length=16)
    name: str = Field(min_length=1, max_length=64)
    markets: list[str] = Field(default_factory=list)
    actor: Actor


class LanguageArchiveRequest(BaseModel):
    actor: Actor


class TargetLanguagesRequest(BaseModel):
    """operations 设置产品录入侧目标语言（Q58 交集的产品侧）；空列表=未声明/不限。"""

    languages: list[str] = Field(default_factory=list)
    actor: Actor


class ContentLanguageView(BaseModel):
    code: str
    name: str
    markets: list[str]
    status: str

