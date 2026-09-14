"""段7/8 静态底表 Pydantic 契约。"""

from pydantic import BaseModel, Field

from app.core.actor import Actor


class SlotItem(BaseModel):
    platform: str
    code: str
    name: str
    slot_type: str
    chars_max: int | None = Field(default=None, ge=0)
    dur_min: int | None = Field(default=None, ge=0)
    dur_max: int | None = Field(default=None, ge=0)
    traffic: float = Field(default=0, ge=0, le=100)
    safe: float = Field(default=0, ge=0, le=100)
    conv: float = Field(default=0, ge=0, le=100)
    load: float = Field(default=0, ge=0, le=100)
    risk: str | None = None
    gate: str = "approved"
    source_url: str | None = None


class SlotUpsert(BaseModel):
    item: SlotItem
    actor: Actor


class FitWeightPut(BaseModel):
    goal: str
    weights: dict
    actor: Actor


class RuleItem(BaseModel):
    selector_level: str
    platform: str | None = None
    slot_type: str | None = None
    slot_id: str | None = None
    country: str | None = None
    effect: str
    note: str | None = None


class RuleCreate(BaseModel):
    item: RuleItem
    overwrite: bool = False
    actor: Actor


class RuleUpdate(BaseModel):
    item: RuleItem
    actor: Actor


class SlotTypeDefaultPut(BaseModel):
    slot_type: str
    daily_limit_min: int | None = Field(default=None, ge=0)
    daily_limit_max: int | None = Field(default=None, ge=0)
    defaults: dict = Field(default_factory=dict)
    actor: Actor


class PcpCreate(BaseModel):
    platform: str
    template_code: str | None = None
    weights: dict | None = None
    actor: Actor


class PcpUpdate(BaseModel):
    weights: dict
    actor: Actor


class ActorOnly(BaseModel):
    actor: Actor
