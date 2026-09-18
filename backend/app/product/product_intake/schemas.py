from datetime import datetime

from pydantic import BaseModel, Field

from app.core.actor import Actor

__all__ = ["Actor"]


class IntakeCreate(BaseModel):
    tenant_id: str
    profile: dict[str, str] = Field(default_factory=dict)


class IntakeProfilePatch(BaseModel):
    profile: dict[str, str]
    actor: Actor


class IntakeTargetLanguagesPatch(BaseModel):
    """B3/Q122：客户在段1 录入页设置产品目标语言（Q58 交集的产品侧，客户口径无运营闸）。"""

    languages: list[str] = Field(default_factory=list)
    actor: Actor


class IntakeTransition(BaseModel):
    event: str
    actor: Actor
    # 冷启动支线关联的 B2 类目候选单（wf01_cold_start 时可带）。
    category_pending_id: str | None = None


class IntakeView(BaseModel):
    intake_id: str
    tenant_id: str
    status: str
    profile: dict[str, str]
    category_pending_id: str | None = None


class IntakeList(BaseModel):
    items: list[IntakeView]
    total: int
    limit: int
    offset: int


class OpsIntakeView(IntakeView):
    # Q107：运营跨租户队列行在租户内 IntakeView 之上加创建时间。
    created_at: datetime


class OpsIntakeList(BaseModel):
    items: list[OpsIntakeView]
    total: int
    limit: int
    offset: int


class IntakeOverview(BaseModel):
    total: int
    by_status: dict[str, int]


class ProductSpaceView(BaseModel):
    product_space_id: str
    tenant_id: str
    intake_id: str
    lifecycle: str
    profile_snapshot: dict[str, str]
    # Q119/B3：产品目标语言（NULL/空 = 未声明、不收窄语言交集）。
    target_languages: list[str] | None = None
