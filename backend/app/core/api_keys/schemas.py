from datetime import datetime

from pydantic import BaseModel, Field

from app.core.actor import Actor


class AgentKeyIssueRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    actor: Actor


class AgentKeyRevokeRequest(BaseModel):
    actor: Actor


class AgentKeyView(BaseModel):
    key_id: str
    name: str
    key_prefix: str
    status: str
    created_at: datetime
    last_used_at: datetime | None = None


class AgentKeyIssued(AgentKeyView):
    # 明文仅此一次返回；后台之后不可再读（Q88-2）。
    secret: str
