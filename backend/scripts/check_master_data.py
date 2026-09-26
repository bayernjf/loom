"""主数据回填自检器（Q210）。

业务方按 docs/19 §0.2「最小可发证清单」回填四表后，用本脚本确认是否够产出
**1 个真实 final_id**。本脚本**不代填任何业务数据、不臆造**——只读 DB，并据
docs/19 §0.2 与发证解析器（`app/final/final_whitelist/service.py` 的
`_resolve_slot` / `_resolve_pcp` / `_resolve_packages`）逐条判定。

判定口径与 resolver 完全一致：**只看 `status == "active"`，不看 `gate` 档**：
- 至少 1 个 active `publish_slots`（取其 `platform` 作为候选发布平台）；
- 该 `platform` 下至少 1 个 active `pcp_weight_tables`（product_space×tenant×platform）；
- 至少 1 个 active `content_goals`（发证时会 `_validate_goal`）；
- 对某个 (product_space, tenant, platform, goal) 组合，CSP/CSTP/CEP 三种 active
  `packages` 齐备（resolver 的 `MaterialMissing` 条件）。

四类齐备 ⇒「可发证」。

另报 `cp_law_sensitive_domains` 是否为零行：零行 ⇒ Guard⑥ 当前走"无法审单即放行"
默认分支（docs/19 §0.2：**可配置项、非永久豁免**，首批选产品应避开拟启用敏感
类目的行业）——这是提示，不影响"可发证"判定。

退出码：缺任一必填项 ⇒ 1；齐备 ⇒ 0。

用法：
    python scripts/check_master_data.py [--json]
DSN 取 `LOOM_DATABASE_DSN`（缺省用 `app.core.config.get_settings().database_dsn`）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db import Base
from app.decision.compliance_center.models import CpLawSensitiveDomain
from app.decision.layer_strategy.models import KIND_CEP, KIND_CSP, KIND_CSTP, Package
from app.platform.platform_adaptation.models import PcpWeightTable, PublishSlot
from app.product.condition.models import ContentGoal

_PACKAGE_KINDS = (KIND_CSP, KIND_CSTP, KIND_CEP)
_REQUIRED_TABLES = (
    PublishSlot.__table__,
    PcpWeightTable.__table__,
    Package.__table__,
    ContentGoal.__table__,
    CpLawSensitiveDomain.__table__,
)


async def collect_facts(session) -> dict:
    """只读采集五张表的 active 事实（不判定、不写）。"""
    slots = (
        await session.execute(
            select(PublishSlot.slot_id, PublishSlot.platform).where(
                PublishSlot.status == "active"
            )
        )
    ).all()
    pcps = (
        await session.execute(
            select(
                PcpWeightTable.product_space_id,
                PcpWeightTable.tenant_id,
                PcpWeightTable.platform,
            ).where(PcpWeightTable.status == "active")
        )
    ).all()
    pkgs = (
        await session.execute(
            select(
                Package.product_space_id,
                Package.tenant_id,
                Package.platform,
                Package.goal,
                Package.kind,
            ).where(Package.status == "active")
        )
    ).all()
    goals = (
        await session.execute(
            select(ContentGoal.code).where(ContentGoal.status == "active")
        )
    ).all()
    sens_count = (
        await session.execute(select(func.count()).select_from(CpLawSensitiveDomain))
    ).scalar_one()

    return {
        "slots": slots,
        "pcps": pcps,
        "packages": pkgs,
        "goals": goals,
        "sensitive_domains_count": int(sens_count or 0),
    }


def evaluate(facts: dict) -> dict:
    """把采集到的 active 事实判定成"是否可发证"+ 缺口清单（纯函数，无 DB 依赖）。

    返回结构：
        ready: bool
        ready_combo: dict | None   — 一个可发证的 (ps_id, tenant, platform, goal) 组合
        missing_required: list[str] — 绝对必填项里为零的类别（human 文案）
        gaps: list[str]            — 进一步定位：有平台/PCP 但缺三包的情形
        sensitive_domains_zero: bool
        counts: dict               — 各类 active 计数（便于回填方核对）
    """
    slots = facts["slots"]
    pcps = facts["pcps"]
    pkgs = facts["packages"]
    goals = {g for (g,) in facts["goals"]}
    sens_zero = facts["sensitive_domains_count"] == 0

    slot_platforms = {p for (_, p) in slots}
    # package 索引：(ps_id, tenant, platform, goal) -> {kind, ...}
    pkg_index: dict[tuple[str, str, str, str], set[str]] = {}
    for ps_id, tenant, platform, goal, kind in pkgs:
        pkg_index.setdefault((ps_id, tenant, platform, goal), set()).add(kind)

    # 候选 combo：slot 决定 platform；pcp 决定 (ps_id, tenant)；goal 取 active。
    ready_combo: dict | None = None
    gaps: list[str] = []
    for ps_id, tenant, platform in pcps:
        if platform not in slot_platforms:
            # 该 PCP 的平台上没有 active 发布位——resolver 会因 slot.platform 不符而失败。
            gaps.append(
                f"PCP {ps_id}/{tenant}/{platform} 没有同平台的 active 发布位"
            )
            continue
        for goal in goals:
            kinds = pkg_index.get((ps_id, tenant, platform, goal))
            if kinds is not None and kinds == set(_PACKAGE_KINDS):
                ready_combo = {
                    "product_space_id": ps_id,
                    "tenant_id": tenant,
                    "platform": platform,
                    "goal": goal,
                }
                break
        if ready_combo is not None:
            break

    missing_required: list[str] = []
    if not slots:
        missing_required.append("publish_slots（无 active 发布位）")
    if not pcps:
        missing_required.append("pcp_weight_tables（无 active PCP）")
    if not goals:
        missing_required.append("content_goals（无 active 目的字典）")
    if not pkgs:
        missing_required.append("packages（无 active 三包）")
    if not ready_combo and not missing_required and gaps:
        # 平台/PCP/三包都有，但没凑出完整组合——进一步提示。
        missing_required.append(
            "可发证的 (platform, PCP, goal) 组合：三包未齐备或发布位平台不匹配"
        )

    ready = ready_combo is not None and not missing_required
    return {
        "ready": ready,
        "ready_combo": ready_combo,
        "missing_required": missing_required,
        "gaps": gaps,
        "sensitive_domains_zero": sens_zero,
        "counts": {
            "publish_slots_active": len(slots),
            "pcp_weight_tables_active": len(pcps),
            "packages_active": len(pkgs),
            "content_goals_active": len(goals),
            "cp_law_sensitive_domains": facts["sensitive_domains_count"],
        },
    }


def _format_report(result: dict) -> str:
    lines = []
    counts = result["counts"]
    lines.append("== 主数据回填自检（docs/19 §0.2 最小可发证清单）==")
    lines.append(
        f"  publish_slots(active)={counts['publish_slots_active']}  "
        f"pcp_weight_tables(active)={counts['pcp_weight_tables_active']}  "
        f"packages(active)={counts['packages_active']}  "
        f"content_goals(active)={counts['content_goals_active']}"
    )
    lines.append(
        f"  cp_law_sensitive_domains={counts['cp_law_sensitive_domains']}"
        + ("  ⚠ 零行⇒Guard⑥ 默认放行（可配置、非永久豁免）" if result["sensitive_domains_zero"] else "")
    )
    if result["ready"]:
        c = result["ready_combo"]
        lines.append(
            "✅ 已可发证：找到可发证组合 "
            f"(product_space={c['product_space_id']}, tenant={c['tenant_id']}, "
            f"platform={c['platform']}, goal={c['goal']})"
        )
    else:
        lines.append("❌ 尚不可发证，缺口：")
        for m in result["missing_required"]:
            lines.append(f"   - {m}")
        for g in result["gaps"][:10]:
            lines.append(f"   · {g}")
    return "\n".join(lines)


async def _run(dsn: str) -> dict:
    engine = create_async_engine(dsn)
    async with engine.begin() as conn:
        # 仅确保本脚本关心的五张表存在（不碰其余 schema，不依赖迁移）。
        await conn.run_sync(Base.metadata.create_all, tables=_REQUIRED_TABLES)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        facts = await collect_facts(session)
    await engine.dispose()
    return evaluate(facts)


def main() -> int:
    parser = argparse.ArgumentParser(description="主数据回填自检器")
    parser.add_argument(
        "--json", action="store_true", help="只输出 JSON（便于自动化解析）"
    )
    parser.add_argument(
        "--dsn", default=None, help="DB DSN（缺省取 LOOM_DATABASE_DSN / settings）"
    )
    args = parser.parse_args()

    dsn = args.dsn or get_settings().database_dsn
    result = asyncio.run(_run(dsn))
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(_format_report(result))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
