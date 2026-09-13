"""段4 Pydantic 契约。Actor 复用段1口径。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.actor import Actor

RiskLevel = Literal["critical", "high", "medium", "low"]


# ---- Q48 合规词库 ----

class WordlistItem(BaseModel):
    word: str = Field(min_length=1)
    level: Literal["critical", "high"]
    action: Literal["ban", "downgrade"]
    downgrade_target: str | None = None
    country: str | None = None
    industry: str | None = None


class WordlistUpsert(BaseModel):
    item: WordlistItem
    actor: Actor


# ---- WF-03 拓展批次 ----

class AtomItem(BaseModel):
    content: str = Field(min_length=1)
    dimension_id: str
    # 未命中词表时的 AI 判级（Q17 兜底轨道）。
    ai_risk: RiskLevel = "low"
    affinity: float | None = Field(default=None, ge=0, le=1)
    evidence: str | None = None
    fact_type: Literal[
        "capacity", "ingredient", "concentration", "wart_type", "brand"
    ] | None = None
    cluster_id: str | None = None


class BatchSubmitRequest(BaseModel):
    items: list[AtomItem] = Field(min_length=1)
    source: Literal["ai", "manual"] = "ai"
    batch_size: int | None = Field(default=None, ge=1)
    actor: Actor


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1)
    actor: Actor


class EvidenceRequest(BaseModel):
    evidence: str = Field(min_length=1)
    actor: Actor


class ClusterResolveRequest(BaseModel):
    keeper_candidate_id: str
    actor: Actor


class BatchApproveRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)
    actor: Actor


class RiskOverrideRequest(BaseModel):
    level: RiskLevel
    reason: str = Field(min_length=1)
    actor: Actor


class LifecycleRequest(BaseModel):
    actor: Actor
