"""skill7 通道 Pydantic 契约（05 §1.4 切片 e 登记）。"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.actor import Actor

CandidateState = Literal[
    "pending_review", "confirmed", "modified", "rejected", "applied", "archived"
]

# WF-07 AI 选包四场景（docs/12 §3.2 #21–#24，Q328 操作面）。
Wf07Scene = Literal[
    "PT-CONTENT-GOAL-PLAN",
    "PT-STRUCT-MATCH",
    "PT-TONE-STYLE",
    "PT-CONTENT-GOAL-TAG",
]


class AiSelectSuggestRequest(BaseModel):
    """Q328：组装工作台「AI 选包建议」触发体。

    按当前 PS×platform×slot 组装有界变量后经模型网关 synthetic 路由产出候选；
    端点层前置闸：PS 存在（404）、TONE/TAG 场景缺 goal、TAG 场景缺 body 由
    合成路由 error 形态按 422 强校验（与 docs/12 §3.2 强校验一致）。
    """

    scene: Wf07Scene
    product_space_id: str = Field(min_length=1)
    slot_id: str | None = Field(default=None, min_length=1)
    goal: str | None = Field(default=None, min_length=1)
    body: str | None = Field(default=None, min_length=1)
    actor: Actor


class CandidateInput(BaseModel):
    # target_type 与 WF 步骤声明的 candidate_target 对齐（按 WF 泛化）：
    # pwc_combo（WF-04）/ field_plan（WF-02，Q78）/ c1_recognition（WF-01，Q79）
    # / atom_batch（WF-03，Q80）/ c7_layer4（WF-01 TYPE-MATCH，Q81）
    # / package_draft（WF-07 AI 选包，Q328）。
    target_type: Literal[
        "pwc_combo", "field_plan", "c1_recognition", "atom_batch", "c7_layer4",
        "package_draft",
    ]
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
