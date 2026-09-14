"""段9 三包配置实例 Pydantic 契约。"""

from pydantic import BaseModel, Field

from app.core.actor import Actor


class PackageItem(BaseModel):
    kind: str
    platform: str
    goal: str
    payload: dict
    conf: float | None = Field(default=None, ge=0, le=1)


class PackageCreate(BaseModel):
    item: PackageItem
    actor: Actor


class PackageUpdate(BaseModel):
    payload: dict
    conf: float | None = Field(default=None, ge=0, le=1)
    actor: Actor


class ActorOnly(BaseModel):
    actor: Actor
