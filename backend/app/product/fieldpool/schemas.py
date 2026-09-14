"""段3 Pydantic 契约。Actor 复用段1口径。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.product.fieldpool import planning
from app.product.product_intake.schemas import Actor


class RouteItem(BaseModel):
    route: str
    name: str
    enabled: bool = True
    sort_order: int = 0


class RouteUpsert(BaseModel):
    item: RouteItem
    actor: Actor


class DimensionItem(BaseModel):
    field_name: str = Field(min_length=1)
    role: str
    source_route: str
    confidence: float = Field(ge=0, le=1)
    source_ref: str | None = None
    fid: str | None = None
    similarity: float | None = Field(default=None, ge=0, le=1)
    related_fid: str | None = None
    definition: str | None = None


class PlanSubmitRequest(BaseModel):
    dimensions: list[DimensionItem] = Field(min_length=1)
    target_atom_min: int = Field(default_factory=planning.target_atom_min_default)
    target_atom_max: int = Field(default_factory=planning.target_atom_max_default)
    actor: Actor


class GateDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = None
    actor: Actor


class RestoreRequest(BaseModel):
    actor: Actor


class PromoteRequest(BaseModel):
    fid: str = Field(min_length=1)
    cat: str = "extension"  # G2 cat 完整取值原文未给（待基准 HTML），非 common 占位档
    actor: Actor
