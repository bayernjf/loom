"""skill7 通道 Pydantic 契约（05 §1.4 切片 e 登记）。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.actor import Actor

CandidateState = Literal[
    "pending_review", "confirmed", "modified", "rejected", "applied", "archived"
]


class CandidateInput(BaseModel):
    # target_type 与 WF 步骤声明的 candidate_target 对齐（Q78 起按 WF 泛化）：
    # pwc_combo（WF-04）/ field_plan（WF-02）。
    target_type: Literal["pwc_combo", "field_plan"]
    payload: dict


class DeliverRunRequest(BaseModel):
    skill_id: str = Field(min_length=1)
    wf_id: str | None = None
    product_space_id: str = Field(min_length=1)
    input: dict | None = None
    output: dict | None = None
    candidates: list[CandidateInput] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    actor: Actor


class CandidateDecisionRequest(BaseModel):
    decision: Literal["confirmed", "modified", "rejected"]
    # modified 时必给替换 payload；confirmed/rejected 忽略。
    payload: dict | None = None
    reason: str | None = None
    actor: Actor
