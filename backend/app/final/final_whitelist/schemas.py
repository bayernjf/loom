"""段11 FCW 组装 Pydantic 契约（Q55：任务驱动批量 + 手动单条）。"""

from pydantic import BaseModel, Field

from app.core.actor import Actor


class AssemblyManual(BaseModel):
    """手动单条发证：指定冻结版（缺省取 PS 当前 active 版）与发布位。"""

    product_space_id: str
    pws_id: str | None = None
    platform: str
    slot_id: str
    goal: str
    country: str | None = None
    actor: Actor


class AssemblyTaskCreate(BaseModel):
    """Q55 任务：产品×平台×目的×数量，系统机械配料逐条过 Guard。"""

    product_space_id: str
    pws_id: str | None = None
    platform: str
    goal: str
    country: str | None = None
    count: int = Field(ge=1, le=200)
    slot_ids: list[str] | None = None
    actor: Actor
