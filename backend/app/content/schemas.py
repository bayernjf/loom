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

