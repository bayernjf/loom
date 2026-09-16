"""段10 合规清洗 Pydantic 契约。"""

from pydantic import BaseModel

from app.core.actor import Actor


class CcrMarketView(BaseModel):
    # Q101：每市场最新一行 CCR 报告（None country=底座通用判定）。
    country: str | None
    status: str
    block_required: bool
    created_at: str | None
    bans: list[dict]
    downgrades: list[dict]


class CcrOverview(BaseModel):
    worst_status: str
    block_required: bool
    latest_at: str | None
    markets: list[CcrMarketView]


class LawReviewView(BaseModel):
    status: str
    domain: str
    conclusion: str | None
    decided_at: str | None


class ComplianceOverviewItem(BaseModel):
    pws_id: str
    product_space_id: str
    intake_id: str | None
    product_name: str | None
    version: str
    ccr: CcrOverview | None
    law_review: LawReviewView | None


class ComplianceOverview(BaseModel):
    items: list[ComplianceOverviewItem]


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
