from datetime import datetime

from pydantic import BaseModel

from app.core.actor import Actor

__all__ = ["Actor"]


class TenantProvisionRequest(BaseModel):
    tenant_id: str
    name: str | None = None
    plan: str = "trial"
    actor: Actor


class TenantChangePlanRequest(BaseModel):
    plan: str
    actor: Actor


class TenantLifecycleRequest(BaseModel):
    actor: Actor


class TenantView(BaseModel):
    tenant_id: str
    name: str | None
    plan: str
    status: str
    monthly_token_quota: int | None
    detail: dict
    created_at: datetime | None = None


class TenantDetailView(TenantView):
    # Q95：Onboarding 进度为派生口径（无引导状态机/无引导表）。
    onboarding: dict
