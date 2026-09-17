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
