from datetime import datetime

from pydantic import BaseModel, Field

from app.core.actor import Actor


class StaffKeyIssueRequest(BaseModel):
    staff_id: str = Field(min_length=1, max_length=64)
    staff_name: str = Field(min_length=1, max_length=128)
    roles: list[str] = Field(min_length=1)
    actor: Actor


class StaffKeyRevokeRequest(BaseModel):
    actor: Actor


class StaffKeyView(BaseModel):
    key_id: str
    staff_id: str
    staff_name: str
    roles: list[str]
    key_prefix: str
    status: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class StaffKeyIssued(StaffKeyView):
    # 明文仅此一次返回；后台之后不可再读（同 Q88-2）。
    secret: str


class StaffMe(BaseModel):
    staff_id: str
    staff_name: str
    roles: list[str]
