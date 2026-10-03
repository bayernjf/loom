"""段9 三包配置实例 + Q262 layerSpaces 通用底座 Pydantic 契约。"""

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


# --- Q262 layerSpaces（Q46） ---


class LayerSpaceItemCreate(BaseModel):
    layer_id: str
    dimension: str
    name: str
    status: str | None = Field(default=None)
    actor: Actor


class LayerSpaceItemUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    # Q46：被活跃配方引用时，变更须显式确认影响面（Gate，工程口径【实现补】）。
    impact_confirmed: bool = False
    actor: Actor


class LayerSpaceItemArchive(BaseModel):
    impact_confirmed: bool = False
    actor: Actor
