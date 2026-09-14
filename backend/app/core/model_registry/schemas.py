"""模型注册表/场景路由/Key/Prompt 管理 Pydantic 契约（Q67/Q82，05 §1.4 实现登记）。"""

from pydantic import BaseModel, Field

from app.core.actor import Actor


class AIModelCreate(BaseModel):
    model_code: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=32)
    input_price_per_1m: float = Field(default=0, ge=0)
    output_price_per_1m: float = Field(default=0, ge=0)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    daily_budget: float | None = Field(default=None, ge=0)
    fallback_model_id: str | None = None
    actor: Actor


class AIModelPatch(BaseModel):
    input_price_per_1m: float | None = Field(default=None, ge=0)
    output_price_per_1m: float | None = Field(default=None, ge=0)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    daily_budget: float | None = Field(default=None, ge=0)
    status: str | None = None  # active / disabled
    fallback_model_id: str | None = None
    actor: Actor


class AIModelView(BaseModel):
    model_id: str
    model_code: str
    provider: str
    input_price_per_1m: float
    output_price_per_1m: float
    currency_code: str | None
    daily_budget: float | None
    status: str
    fallback_model_id: str | None
    has_active_key: bool = False


class KeyCreate(BaseModel):
    secret: str = Field(min_length=8)
    actor: Actor


class KeyView(BaseModel):
    key_id: str
    model_id: str
    fingerprint: str
    status: str


class SceneRouteUpsert(BaseModel):
    model_id: str = Field(min_length=1)
    actor: Actor


class SceneRouteView(BaseModel):
    scene: str
    model_id: str


class PromptPublish(BaseModel):
    template: str = Field(min_length=1)
    change_note: str | None = None
    variables: dict = Field(default_factory=dict)
    actor: Actor


class PromptView(BaseModel):
    skill_id: str
    current_version: str


class PromptVersionView(BaseModel):
    version_id: str
    skill_id: str
    version: str
    change_note: str | None
    created_by: str | None
    # 列表不带 template 全文，单取另开端点（避免历史 Prompt 批量回显过大）。


class PromptVersionDetail(PromptVersionView):
    template: str
    variables: dict


class RecognizeInvokeRequest(BaseModel):
    actor: Actor
