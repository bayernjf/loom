from pydantic import BaseModel, Field


class Actor(BaseModel):
    id: str
    roles: list[str] = Field(default_factory=list)


class IntakeCreate(BaseModel):
    tenant_id: str
    profile: dict[str, str] = Field(default_factory=dict)


class IntakeProfilePatch(BaseModel):
    profile: dict[str, str]
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


class ProductSpaceView(BaseModel):
    product_space_id: str
    tenant_id: str
    intake_id: str
    lifecycle: str
    profile_snapshot: dict[str, str]
