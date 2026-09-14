from pydantic import BaseModel

from app.core.actor import Actor


class ConfigUpdate(BaseModel):
    value: object
    change_note: str | None = None
    actor: Actor


class ConfigRollback(BaseModel):
    target_version: int
    change_note: str | None = None
    actor: Actor
