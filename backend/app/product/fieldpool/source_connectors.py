"""DIM-SOURCE 连接器 spike：G1 类目模板 / 合规风险词条 → DIM-MERGE 有界来源。

L-07 当前打通两条可复现来源：
- ``category_template``：产品空间绑定类目的已审核 G1 模板字段；
- ``compliance_risk``：本机统一合规词库中当前生效、适用于本产品行业/全球的词条。

两条连接器均只读、不触网、不产生候选；缺绑定/未审核/字段失效/词条过期均
fail-closed 为空，不编造来源。其余五路外部连接器不在本模块内。
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.compliance_wordlist.models import ComplianceWordlistEntry
from app.product.case_evidence.models import CaseEvidence
from app.product.modeling.models import G1Category, G1CategoryTemplate
from app.product.product_intake.models import G2Field, ProductSpace

CATEGORY_TEMPLATE_ROUTE = "category_template"
COMPLIANCE_RISK_ROUTE = "compliance_risk"
CASE_EVIDENCE_ROUTE = "case_evidence"
TEMPLATE_STATUS_APPROVED = "approved"
G2_STATUS_ACTIVE = "active"
WORDLIST_STATUS_ACTIVE = "active"
MAX_COMPLIANCE_RISK_ENTRIES = 20
MAX_CASE_EVIDENCE_ENTRIES = 20
CATEGORY_SOURCE_REF_PREFIX = f"{CATEGORY_TEMPLATE_ROUTE}:"
COMPLIANCE_SOURCE_REF_PREFIX = f"{COMPLIANCE_RISK_ROUTE}:"
CASE_EVIDENCE_SOURCE_REF_PREFIX = f"{CASE_EVIDENCE_ROUTE}:"


@dataclass(frozen=True)
class CategoryTemplateEntry:
    """一条类目模板字段来源；``source_ref`` 直接进 DIM-MERGE 维度依据。"""

    category_id: str
    category_name: str
    fid: str
    field_name: str

    @property
    def source_ref(self) -> str:
        return f"{CATEGORY_SOURCE_REF_PREFIX}{self.fid}"


async def load_category_template_entries(
    session: AsyncSession, product_space: ProductSpace
) -> list[CategoryTemplateEntry]:
    """读取产品空间所属类目的已审核模板字段；缺绑定/未审核/字段失效均跳过。"""
    if not product_space.category_node_id:
        return []

    template_stmt = (
        select(G1Category.name, G1CategoryTemplate.field_list)
        .join(
            G1CategoryTemplate,
            G1CategoryTemplate.category_id == G1Category.category_id,
        )
        .where(
            G1Category.category_id == product_space.category_node_id,
            G1CategoryTemplate.status == TEMPLATE_STATUS_APPROVED,
        )
        .limit(1)
    )
    template_row = (await session.execute(template_stmt)).first()
    if template_row is None:
        return []

    category_name, raw_field_list = template_row
    fids = [fid for fid in (raw_field_list or []) if isinstance(fid, str) and fid]
    if not fids:
        return []

    field_rows = (
        await session.execute(
            select(G2Field.fid, G2Field.field_name).where(
                G2Field.fid.in_(fids), G2Field.status == G2_STATUS_ACTIVE
            )
        )
    ).all()
    name_by_fid = {fid: field_name for fid, field_name in field_rows}

    return [
        CategoryTemplateEntry(
            category_id=product_space.category_node_id,
            category_name=category_name,
            fid=fid,
            field_name=name_by_fid[fid],
        )
        for fid in fids
        if fid in name_by_fid
    ]


def format_category_template_context(entries: list[CategoryTemplateEntry]) -> str:
    """把类目模板字段渲染成 DIM-MERGE 提示词文本块；空列表给「（无）」。"""
    if not entries:
        return "（无）"
    first = entries[0]
    lines = [f"类目：{first.category_name}（{first.category_id}）"]
    for entry in entries:
        lines.append(
            f"- {entry.field_name} | fid={entry.fid} | source_ref={entry.source_ref}"
        )
    return "\n".join(lines)


@dataclass(frozen=True)
class ComplianceRiskEntry:
    """一条合规风险词条来源；``source_ref`` 用 entry_id，避免词面重复。"""

    entry_id: str
    word: str
    level: str
    action: str
    downgrade_target: str | None
    industry: str | None
    country: str | None
    layer: str

    @property
    def source_ref(self) -> str:
        return f"{COMPLIANCE_SOURCE_REF_PREFIX}{self.entry_id}"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_effective(entry: ComplianceWordlistEntry, now: datetime) -> bool:
    start = _as_utc(entry.effective_from)
    end = _as_utc(entry.effective_until)
    return (start is None or start <= now) and (end is None or now < end)


def _severity_rank(entry: ComplianceWordlistEntry) -> tuple[int, str, str]:
    return ({"critical": 0, "high": 1}.get(entry.level, 2), entry.word, entry.entry_id)


async def load_compliance_risk_entries(
    session: AsyncSession, product_space: ProductSpace
) -> list[ComplianceRiskEntry]:
    """读取当前生效、适用本产品行业/全球的合规词条；最多 20 条。

    country 定向词条暂不注入：ProductSpace 尚无国家字段，无法可靠匹配，
    fail-closed 留给后续国家维度。
    """
    industry_filter = (
        or_(
            ComplianceWordlistEntry.industry.is_(None),
            ComplianceWordlistEntry.industry == product_space.industry_tag,
        )
        if product_space.industry_tag
        else ComplianceWordlistEntry.industry.is_(None)
    )
    rows = (
        await session.scalars(
            select(ComplianceWordlistEntry).where(
                ComplianceWordlistEntry.status == WORDLIST_STATUS_ACTIVE,
                ComplianceWordlistEntry.country.is_(None),
                industry_filter,
            )
        )
    ).all()
    now = datetime.now(UTC)
    effective = [row for row in rows if _is_effective(row, now)]
    effective.sort(key=_severity_rank)

    return [
        ComplianceRiskEntry(
            entry_id=entry.entry_id,
            word=entry.word,
            level=entry.level,
            action=entry.action,
            downgrade_target=entry.downgrade_target,
            industry=entry.industry,
            country=entry.country,
            layer=entry.layer,
        )
        for entry in effective[:MAX_COMPLIANCE_RISK_ENTRIES]
    ]


def format_compliance_risk_context(entries: list[ComplianceRiskEntry]) -> str:
    """把合规词条渲染成 DIM-MERGE 提示词文本块；空列表给「（无）」。"""
    if not entries:
        return "（无）"
    lines = ["合规词条（仅列当前生效、适用本产品行业/全球的词条）："]
    for entry in entries:
        parts = [entry.word, f"level={entry.level}", f"action={entry.action}"]
        if entry.downgrade_target:
            parts.append(f"downgrade_to={entry.downgrade_target}")
        if entry.industry:
            parts.append(f"industry={entry.industry}")
        if entry.country:
            parts.append(f"country={entry.country}")
        parts.append(f"source_ref={entry.source_ref}")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


@dataclass(frozen=True)
class CaseEvidenceEntry:
    """一条案例证据来源；``source_ref`` 用 case_id，避免案例内容重复。"""

    case_id: str
    title: str
    content: str
    source_url: str | None
    product_space_id: str | None

    @property
    def source_ref(self) -> str:
        return f"{CASE_EVIDENCE_SOURCE_REF_PREFIX}{self.case_id}"


async def load_case_evidence_entries(
    session: AsyncSession, product_space: ProductSpace
) -> list[CaseEvidenceEntry]:
    """读取该租户 enabled 的通用层 + 本产品专属层案例；最多 20 条。

    fail-closed：缺 tenant 绑定/无案例/未启用均返回空，不编造来源。
    """
    stmt = (
        select(CaseEvidence)
        .where(
            CaseEvidence.tenant_id == product_space.tenant_id,
            CaseEvidence.enabled.is_(True),
        )
        .where(
            or_(
                CaseEvidence.product_space_id.is_(None),
                CaseEvidence.product_space_id == product_space.product_space_id,
            )
        )
        .order_by(
            CaseEvidence.product_space_id.is_(None).desc(),
            CaseEvidence.created_at,
            CaseEvidence.case_id,
        )
        .limit(MAX_CASE_EVIDENCE_ENTRIES)
    )
    rows = (await session.scalars(stmt)).all()
    return [
        CaseEvidenceEntry(
            case_id=row.case_id,
            title=row.title,
            content=row.content,
            source_url=row.source_url,
            product_space_id=row.product_space_id,
        )
        for row in rows
    ]


def format_case_evidence_context(entries: list[CaseEvidenceEntry]) -> str:
    """把案例证据渲染成 DIM-MERGE 提示词文本块；空列表给「（无）」。"""
    if not entries:
        return "（无）"
    lines = ["同类好内容/案例（仅列当前启用、本租户通用或本产品专属的案例）："]
    for entry in entries:
        scope = "通用" if entry.product_space_id is None else "产品专属"
        parts = [f"[{scope}] {entry.title}", entry.content]
        if entry.source_url:
            parts.append(f"url={entry.source_url}")
        parts.append(f"source_ref={entry.source_ref}")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)
