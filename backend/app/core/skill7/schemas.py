"""skill7 通道 Pydantic 契约（05 §1.4 切片 e 登记）。"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.actor import Actor

CandidateState = Literal[
    "pending_review", "confirmed", "modified", "rejected", "applied", "archived"
]


class CandidateInput(BaseModel):
    # target_type 与 WF 步骤声明的 candidate_target 对齐（按 WF 泛化）：
    # pwc_combo（WF-04）/ field_plan（WF-02，Q78）/ c1_recognition（WF-01，Q79）
    # / atom_batch（WF-03，Q80）。
    target_type: Literal["pwc_combo", "field_plan", "c1_recognition", "atom_batch"]
    payload: dict


class DeliverRunRequest(BaseModel):
    skill_id: str = Field(min_length=1)
    wf_id: str | None = None
    # Q79-4：锚点二选一——PS 锚点（WF-02/WF-04）或 intake 锚点（WF-01 段2）。
    product_space_id: str | None = Field(default=None, min_length=1)
    intake_id: str | None = Field(default=None, min_length=1)
    input: dict | None = None
    output: dict | None = None
    candidates: list[CandidateInput] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    actor: Actor

    @model_validator(mode="after")
    def _exactly_one_anchor(self) -> "DeliverRunRequest":
        if (self.product_space_id is None) == (self.intake_id is None):
            raise ValueError("exactly one of product_space_id / intake_id is required")
        return self


class CandidateDecisionRequest(BaseModel):
    decision: Literal["confirmed", "modified", "rejected"]
    # modified 时必给替换 payload；confirmed/rejected 忽略。
    payload: dict | None = None
    reason: str | None = None
    actor: Actor
