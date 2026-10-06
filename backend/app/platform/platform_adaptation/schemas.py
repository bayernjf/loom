"""段7/8 静态底表 Pydantic 契约。"""

from datetime import datetime

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


class PlatformAdapterPreviewRequest(BaseModel):
    """Q296 甲（design-v2-platform-adapter-business §3.1）：只读预览口入参。

    复用 match_rules 的入参形状（platform/slot_type/slot_id/country）＋ PWS 快照
    定位；不带 actor——写身份闸 `require_internal_actor(OPERATIONS)` 返回的已验真
    身份即预览人（只读口不写审计，身份仅回显在 `previewed_by`）。
    """

    pws_snapshot_id: str
    platform: str
    slot_type: str
    slot_id: str | None = None
    country: str | None = None


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


class EventItem(BaseModel):
    """Q37 动态信号事件（平台/发布位/事件类型/严重度/生效期）。

    event_type/severity 取值枚举【原文未给出，待补】，运营录入；slot_id 可空=
    平台级事件；effective_end 可空=长期生效。
    """

    platform: str
    slot_id: str | None = None
    event_type: str
    severity: str
    effective_start: datetime
    effective_end: datetime | None = None
    note: str | None = Field(default=None, max_length=512)


class EventUpsert(BaseModel):
    item: EventItem
    actor: Actor


class RecalcCandidateCreate(BaseModel):
    """Q41 重算候选提交（V1 仅 manual 来源；AI 生成器随 V2 PCP-SCORE）。

    change_list = 变化对照单（Q41：项/旧值/新值/理由）。
    """

    pcp_id: str
    proposed_weights: dict
    change_list: list[dict] = Field(default_factory=list)
    actor: Actor


class CandidateApprove(BaseModel):
    actor: Actor


class CandidateReject(BaseModel):
    reason: str = Field(min_length=1, max_length=512)
    actor: Actor
