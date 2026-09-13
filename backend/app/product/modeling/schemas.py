from pydantic import BaseModel, Field

from app.product.product_intake.schemas import Actor


class SignalWeightItem(BaseModel):
    signal: str
    signal_name: str
    enabled: bool = True
    weight: float = Field(ge=0, le=1)
    scoring_method: str | None = None


class SignalWeightUpdate(BaseModel):
    rows: list[SignalWeightItem]
    actor: Actor


class IndustryItem(BaseModel):
    industry: str
    keywords: list[str] = Field(default_factory=list)
    threshold: float = Field(gt=0, le=1)
    sensitive: bool = False
    enabled: bool = True


class IndustryCreate(IndustryItem):
    is_default: bool = False


class IndustryPatch(BaseModel):
    keywords: list[str] | None = None
    threshold: float | None = Field(default=None, gt=0, le=1)
    sensitive: bool | None = None
    enabled: bool | None = None
    actor: Actor


class IndustryWrite(BaseModel):
    item: IndustryCreate
    actor: Actor


class CategoryCandidate(BaseModel):
    category_id: str
    conf: float = Field(ge=0, le=1)


class C1RecognitionRequest(BaseModel):
    # 每个启用信号一个 0..1 分（WF-01 Skill 提取结果；AI 通道随 M10 接入）。
    signals: dict[str, float]
    candidates: list[CategoryCandidate] = Field(default_factory=list)
    industry: str | None = None
    # 低置信分支关联 B2 新类目候选单（Q5）。
    category_pending_id: str | None = None
    actor: Actor


class C1RecognitionView(BaseModel):
    record_id: str
    conf: float
    industry: str
    branch: str
    top_gap: float | None
    intake_status: str
    todo_id: str | None = None


class OpsDecisionRequest(BaseModel):
    # select=运营选定候选类目；reject_all=候选都不对，转 cold_start（Q4）。
    decision: str  # select / reject_all
    category_id: str | None = None
    category_pending_id: str | None = None
    actor: Actor


class TodoView(BaseModel):
    todo_id: str
    todo_type: str
    entity_id: str
    status: str
    due_at: str
    escalated_at: str | None = None


class CategoryCreate(BaseModel):
    name: str
    parent_id: str | None = None


class TemplateUpsert(BaseModel):
    field_list: list[str]
    status: str = "draft"  # draft / approved
    actor: Actor


class C7ResolveRequest(BaseModel):
    category_id: str
    # 该类目必填字段 fid 集（生产环境由 WF-01 TYPE-MATCH 产出，AI 通道随 M10）。
    required_fids: list[str] = Field(default_factory=list)
    # Layer4 模拟 Skill 新字段提案；只允许进候选，禁止带 fid:'-'（Q68）。
    l4_proposals: list[dict] = Field(default_factory=list)
    actor: Actor


class C7RunView(BaseModel):
    run_id: str
    layer: int
    field_list: list
    candidate_ids: list[str] = Field(default_factory=list)
