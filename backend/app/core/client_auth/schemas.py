from datetime import datetime

from pydantic import BaseModel, Field

from app.core.actor import Actor


class ClientKeyIssueRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    client_name: str = Field(min_length=1, max_length=128)
    actor: Actor


class ClientKeyRevokeRequest(BaseModel):
    actor: Actor


class ClientKeyView(BaseModel):
    token_id: str
    tenant_id: str
    client_name: str
    key_prefix: str
    status: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ClientKeyIssued(ClientKeyView):
    # 明文仅此一次返回；后台之后不可再读（同 staff/agent key 口径）。
    secret: str
