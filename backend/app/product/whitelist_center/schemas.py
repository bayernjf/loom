"""段6 Pydantic schemas（开发补规格，占位 PT-PWS-FREEZE 见 12 #15）。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.actor import Actor

RefreezeReasonCode = Literal[
    "atom_compliance_suspend",
    "atom_deprecated",
    "wordlist_hit",
    "product_fact_change",
    "asset_increment",
    "unrelated_change",
]


class ReadinessEvaluateRequest(BaseModel):
    actor: Actor


class FreezeRequest(BaseModel):
    actor: Actor
    # 已有 active 版本时必须给重冻原因（Q29）；首冻留空。
    reason_code: RefreezeReasonCode | None = None
    note: str | None = Field(default=None, max_length=500)


class RevokeRequest(BaseModel):
    actor: Actor
    reason: str = Field(min_length=1, max_length=500)
