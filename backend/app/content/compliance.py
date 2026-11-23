"""Q59 复检第③④项：施工指令核对 + 国家规则核对（v0.1 工程甲案）。

来源：docs/01 §C1.12 + docs/02 Q59 原文 + docs/29 规格草案（2026-11-23 拍板
「工程甲案」先落码再迭代）。

③ 施工指令核对（``review_hits["construction"]``）：
- 降级映射已执行：①词库产出的 downgrade 词条仍原样出现在正文 → 命中；
- 结构指令已落实：CSTP ``payload["struct"]`` 要求正文段数 ≥ 结构部件数；
- 无证外产品事实：确定性承诺词在正文出现但不在 PWS 原子证据中 → 命中。
tone/perspective/explicit/soften 无法机械判定，登记在 ``unchecked``。

④ 国家规则核对（``review_hits["country_rules"]``）：
- 外链：正文 URL + 目标国家外链提示；
- 留资：电话/微信/邮箱等引导词 + CN 个保法 / EU GDPR 告知提示；
- CTA：CEP 指定 cta 而正文找不到 CTA 词 → 指令未落实。

口径（与 Q121 同款）：v0.1 工程口径待业务方/法审校准；全部结果只产 advisory，
不抬 ``block_required``、不阻断 approve、不新增状态。
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import ContentProduct
from app.decision.layer_strategy.models import Package
from app.final.final_whitelist.models import FinalContentWhitelist
from app.product.whitelist_center.models import PwsSnapshot

# 确定性承诺词（v0.1 工程词表，待业务校准）。
CLAIM_WORDS = (
    "保证",
    "根治",
    "100%",
    "百分百",
    "绝对",
    "第一",
    "唯一",
    "零风险",
    "无副作用",
    "永久",
    "包治",
)

# 留资引导词（v0.1 工程词表）。
LEAD_WORDS = (
    "电话",
    "手机号",
    "微信",
    "加v",
    "私信",
    "邮箱",
    "二维码",
    "扫码",
    "联系我",
)

# CTA 词（v0.1 工程词表）。
CTA_WORDS = (
    "立即购买",
    "马上抢",
    "下单",
    "预约",
    "领取",
    "报名",
    "咨询",
    "购买",
    "点击",
)

URL_RE = re.compile(r"https?://[^\s\"'<>）)】]+")

# v0.1 工程口径国家规则种子（待业务方/法审校准）。
RULES_VERSION = "v0.1-engineering"
CN_MARKETS = {"CN", "cn", "ZH", "zh"}
EU_MARKETS = {"DE", "FR", "IT", "ES", "NL", "BE", "AT", "IE", "PT", "FI", "SE", "DK", "PL"}


def split_paragraphs(body: str) -> list[str]:
    """按换行切段（中文文案常用单换行分段）；空串返回空列表。"""
    return [line.strip() for line in (body or "").splitlines() if line.strip()]


def find_urls(body: str) -> list[str]:
    return URL_RE.findall(body or "")


def scan_words(body: str, words: tuple[str, ...]) -> list[str]:
    """大小写不敏感的子串命中；返回命中的词表原文。"""
    haystack = (body or "").casefold()
    return [w for w in words if w.casefold() in haystack]


def _expected_struct_parts(struct: str) -> int:
    """「钩子-论点-收尾」按 `-`/`/`/`→` 切部件；无法切分按 3 处理（v0.1）。"""
    parts = [p for p in re.split(r"[-/→>]", struct) if p.strip()]
    return max(len(parts), 1) if parts else 3


def _country_rule_set(country: str | None) -> str:
    if country in CN_MARKETS:
        return "CN"
    if country in EU_MARKETS:
        return "EU"
    return "generic"


async def run_construction_check(
    session: AsyncSession,
    content: ContentProduct,
    fcw: FinalContentWhitelist,
    word_hits: dict,
) -> dict:
    """③ 施工指令核对。只读 FCW 三层包与 PWS 快照，不改任何状态。"""
    body = content.body or ""
    hits: list[dict] = []

    # a. 降级映射已执行：downgrade 词条仍原样出现 → 降级未施工。
    for item in word_hits.get("downgrades") or []:
        word = str(item.get("word") or "").strip()
        if word and word.casefold() in body.casefold():
            hits.append(
                {
                    "code": "downgrade_not_applied",
                    "word": word,
                    "entry_id": item.get("entry_id"),
                }
            )

    # b. 结构指令：CSTP struct → 正文段数。
    struct = None
    pkg = await session.get(Package, fcw.cstp_package_id)
    if pkg is not None and isinstance(pkg.payload, dict):
        struct = pkg.payload.get("struct")
    paragraphs = split_paragraphs(body)
    structure = {"expected": struct, "paragraphs": len(paragraphs), "satisfied": None}
    if isinstance(struct, str) and struct.strip():
        expected_parts = _expected_struct_parts(struct)
        structure["satisfied"] = len(paragraphs) >= expected_parts
        if not structure["satisfied"]:
            hits.append(
                {
                    "code": "structure_not_applied",
                    "expected": struct,
                    "paragraphs": len(paragraphs),
                }
            )

    # c. 无证外产品事实：承诺词需在 PWS 原子证据中出现。
    atom_text = ""
    pws = await session.get(PwsSnapshot, fcw.pws_id)
    if pws is not None and pws.snapshot:
        atoms = pws.snapshot.get("atoms") or []
        parts = []
        for a in atoms:
            if not isinstance(a, dict):
                continue
            aliases = a.get("aliases") or []
            alias_text = " ".join(str(x) for x in aliases) if isinstance(aliases, list) else str(aliases)
            parts.append(f"{a.get('content', '')} {alias_text}")
        atom_text = " ".join(parts)
    claims = []
    for word in scan_words(body, CLAIM_WORDS):
        matched = word.casefold() in atom_text.casefold()
        claims.append({"word": word, "matched_in_pws": matched})
        if not matched:
            hits.append({"code": "unverified_claim", "word": word})

    return {
        "checked": True,
        "rules_version": RULES_VERSION,
        "hits": hits,
        "structure": structure,
        "claims": claims,
        "unchecked": ["tone", "perspective", "explicit", "soften"],
    }


async def run_country_rule_check(
    session: AsyncSession,
    content: ContentProduct,
    fcw: FinalContentWhitelist,
) -> dict:
    """④ 国家规则核对。v0.1 工程种子规则集，只产提示级命中。"""
    body = content.body or ""
    country = content.country
    rule_set = _country_rule_set(country)
    hits: list[dict] = []

    # a. 外链核对（CN 提示站外链接需按平台外链规则确认）。
    urls = find_urls(body)
    if urls and rule_set == "CN":
        hits.append({"code": "outbound_link", "urls": urls})

    # b. 留资核对（CN 个保法 / EU GDPR 告知提示）。
    lead_words = scan_words(body, LEAD_WORDS)
    if lead_words and rule_set in ("CN", "EU"):
        hits.append(
            {
                "code": "lead_capture_notice",
                "words": lead_words,
                "notice": (
                    "收集个人信息需按个保法告知"
                    if rule_set == "CN"
                    else "lead capture requires GDPR notice"
                ),
            }
        )

    # c. CTA 指令核对：CEP 指定 cta 而正文无 CTA 词。
    cta_spec = None
    pkg = await session.get(Package, fcw.cep_package_id)
    if pkg is not None and isinstance(pkg.payload, dict):
        cta_spec = pkg.payload.get("cta")
    cta_words = scan_words(body, CTA_WORDS)
    if cta_spec and not cta_words:
        hits.append({"code": "cta_not_found", "expected": cta_spec})

    return {
        "checked": True,
        "rules_version": RULES_VERSION,
        "country": country,
        "rule_set": rule_set,
        "hits": hits,
        "urls": urls,
        "lead_words": lead_words,
        "cta_words": cta_words,
    }
