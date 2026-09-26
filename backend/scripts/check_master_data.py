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

**本脚本只读**（Q218 起）：绝不建表、绝不写行；必需表都不在的库直接判「不可用」，不代建 schema。
另检查目标库有没有 `alembic_version` 行——没有就说明它不是迁移建出来的，迁移自带的种子（`content_goals` 5 码、`cp_law_sensitive_domains` 6 个 active 领域、`pcp_templates` 4 套）自然都不在，此时输出的「零」是**建库方式**造成的、不是业务没回填。
退出码：齐备 ⇒ 0；缺任一必填项 ⇒ 1；目标库不是 Loom 迁移库（缺必需表）⇒ 2。

用法：
    python scripts/check_master_data.py [--json]
DSN 取 `LOOM_DATABASE_DSN`（缺省用 `app.core.config.get_settings().database_dsn`）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import func, select, text
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
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


async def is_migration_built(session) -> bool:
    """库是否经 `alembic upgrade head` 建出。

    迁移里带的业务种子（`content_goals` 5 码、`cp_law_sensitive_domains` 6 个 active 领域、
    `pcp_templates` 4 套…）只存在于迁移路径；用 `Base.metadata.create_all` 起的测试/替身库
    一行都没有。不检查这一条，"全零"就会被读成"业务还没回填"，而实际是"库不是这么建的"。
    """
    try:
        return bool((await session.execute(text("SELECT version_num FROM alembic_version"))).all())
    except SQLAlchemyError:  # 表不存在／方言不支持 ⇒ 不是迁移库
        return False


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
    # `migration_built` 缺省为 True：只有采集层显式说"不是迁移库"才降级，避免误伤既有调用方。
    migration_built = facts.pop("migration_built", True)
    warnings: list[str] = []
    if not migration_built:
        warnings.append(
            "此库没有 alembic_version 行 ⇒ 不是经 `alembic upgrade head` 建出的。"
            "迁移自带的业务种子（content_goals 5 码、cp_law_sensitive_domains 6 个 active 领域、"
            "pcp_templates 4 套等）在此库中一行都不会有，本判定的『零』可能来自建库方式而非业务未回填。"
        )
    if facts["sensitive_domains_count"] == 0 and migration_built:
        warnings.append(
            "active 敏感领域为 0：与迁移 0007 的种子（6 个）不符，说明有人清空/停用了敏感领域字典 ⇒ "
            "Guard⑥ 当前不会因敏感领域拦人，这是**可配置态**而非默认态。"
        )
    return {
        "ready": ready,
        "ready_combo": ready_combo,
        "missing_required": missing_required,
        "gaps": gaps,
        "migration_built": migration_built,
        "warnings": warnings,
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
        f"  cp_law_sensitive_domains(active)={counts['cp_law_sensitive_domains']}"
        + ("  ⚠ 与迁移 0007 的 6 个种子不符 ⇒ 字典被清空/停用，Guard⑥ 当前不因敏感领域拦人（可配置态，非默认）"
           if result["sensitive_domains_zero"] else "  （Guard⑥ 会对命中的行业建 48h 法审单）")
    )
    for w in result.get("warnings", []):
        lines.append(f"  ⚠ {w}")
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
    """连接目标库并判定。**本脚本只读**：绝不建表、绝不写行（Q218 起；原先在此处
    `create_all(tables=_REQUIRED_TABLES)`，等于偷偷改业务库的 schema，与文档「只读」不符）。
    """
    engine = create_async_engine(dsn)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            missing = await missing_required_tables(session)
            if missing:
                return {"unusable": missing, "ready": False, "warnings": [],
                        "counts": {}, "missing_required": [], "gaps": []}
            facts = await collect_facts(session)
            facts["migration_built"] = await is_migration_built(session)
    finally:
        await engine.dispose()
    return evaluate(facts)


async def missing_required_tables(session) -> list[str]:
    """返回目标库里**不存在**的必需表名（只查元数据，不建任何东西）。"""

    def _sync(sync_session):
        # AsyncSession.run_sync 传进来的是同步 Session（不是 Connection），故经 get_bind() 拿引擎再 inspect。
        existing = set(sqlalchemy_inspect(sync_session.get_bind()).get_table_names())
        return [tbl.name for tbl in _REQUIRED_TABLES if tbl.name not in existing]

    return await session.run_sync(_sync)


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
    unusable = result.get("unusable")
    if unusable:
        # 退出码 2 与"未回填齐备"（1）分开：这不是业务缺数据，是连的库根本不是 Loom 迁移库。
        msg = (f"目标库缺少必需表：{', '.join(unusable)} ⇒ 这不是经 `alembic upgrade head` 建出的 Loom 库。"
               "本脚本只读、不会代你建表（Q218 起）。")
        if args.json:
            print(json.dumps({"unusable": unusable, "ready": False, "message": msg}, ensure_ascii=False))
        else:
            print(f"⛔ {msg}")
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(_format_report(result))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
