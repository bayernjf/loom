"""段5 Pydantic 契约。Actor 复用段1口径。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.actor import Actor

PwcSource = Literal["ai", "manual", "hybrid"]
GoalCode = Literal["ENGAGEMENT", "CONVERSION", "EDUCATION", "TRUST", "RETENTION"]


class ComboItem(BaseModel):
    # combo[{fp,atom}]：跨字段原子（至少 2 个原子、跨 ≥2 个维度在 service 校验）。
    atom_ids: list[str] = Field(min_length=2)
    goals: list[GoalCode] = Field(default_factory=list)
    weight: float | None = Field(default=None, ge=0, le=1)
    # COMBO-VALIDATE 的两个 AI 分项分（0–1）；WF-04 Skill 通道接入前由结构化入参占位，
    # 缺失即 Q22b"AI 失败"：不出分、转人工 Gate，不凑默认值。
    logic_score: float | None = Field(default=None, ge=0, le=1)
    fit_score: float | None = Field(default=None, ge=0, le=1)
    strategy_refs: list[str] = Field(default_factory=list)
    structure_refs: list[str] = Field(default_factory=list)
    expression_refs: list[str] = Field(default_factory=list)


class FunnelRequest(BaseModel):
    combos: list[ComboItem] = Field(min_length=1)
    source: PwcSource = "ai"
    # Q21 单次产出上限默认 50，运营可在单次请求覆盖；最终截断仍受默认线约束。
    batch_size: int | None = Field(default=None, ge=1)
    actor: Actor


class GateRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = None
    actor: Actor


class ConsumeRequest(BaseModel):
    # Q24/Q71：同 platform+account+slot 去重，按分排序取用。
    platform: str = Field(min_length=1)
    account: str = Field(min_length=1)
    slot: str = Field(min_length=1)
    goals: list[GoalCode] | None = None
    actor: Actor


class HotMarkRequest(BaseModel):
    is_hot: bool
    actor: Actor


class PoolConfigRequest(BaseModel):
    # Q27：NULL=运营显式配"无上限"；取值 ≥1。
    capacity: int | None = Field(default=None, ge=1)
    target_platforms: list[str] = Field(default_factory=list)
    high_reuse_n: int | None = Field(default=None, ge=1)
    actor: Actor


class GoalUpsertRequest(BaseModel):
    code: GoalCode
    color: str | None = Field(default=None, max_length=16)
    ratio_min: float | None = Field(default=None, ge=0, le=1)
    ratio_max: float | None = Field(default=None, ge=0, le=1)
    actor: Actor


class GoalArchiveRequest(BaseModel):
    actor: Actor


class ActorRequest(BaseModel):
    actor: Actor
