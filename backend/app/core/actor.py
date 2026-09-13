"""跨模块统一操作人口径：所有写操作的 actor 入参。"""

from pydantic import BaseModel, Field


class Actor(BaseModel):
    id: str
    roles: list[str] = Field(default_factory=list)
