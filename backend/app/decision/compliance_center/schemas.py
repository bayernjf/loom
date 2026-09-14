"""段10 合规清洗 Pydantic 契约。"""

from pydantic import BaseModel

from app.core.actor import Actor


class DomainItem(BaseModel):
    code: str
    name: str


class DomainUpsert(BaseModel):
    item: DomainItem
    actor: Actor


class DomainArchive(BaseModel):
    actor: Actor


class CcrRun(BaseModel):
    # 分市场独立判（PT-COMPLIANCE-V2.0）：None=底座通用判定。
    country: str | None = None
    actor: Actor


class DowngradeApproval(BaseModel):
    actor: Actor


class LawDecision(BaseModel):
    approved: bool
    conclusion: str | None = None
    actor: Actor
