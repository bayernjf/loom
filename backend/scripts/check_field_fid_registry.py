"""G2 字段 fid 上户口扫描器（Q68 精神的一次性存量处置）。

Q68 定稿（docs/02 §10.15）：「任何进入 `field_list` 的字段必须持合法 G2 fid」——
C7 各层产出/回填字段时只能挑现有 G2 fid，或建 `g2FieldCandidate` 拿候选，**禁止 `fid:'-'` 落库**；
存量 `fid:'-'` 做一次性"上户口"扫描：能匹配 G2 的补 fid，匹配不到的建候选＋挂运营待办
（转正走 Q13 字典管理员权限）。

**写侧那道闸已经在了**（`app/product/modeling/c7.py` 的 `FORBIDDEN_FID = "-"`、
`model_registry/field_plan.py:187` 拒收 `'-'` 与非 active fid）。本脚本补的是**存量那一半**：
库建出来之后扫一遍"黑户落在哪儿、该补还是该建候选"，把处置依据摆出来。

**本脚本只读、不代处置**（同 Q218／check_master_data 的纪律）：

- 绝不写库、绝不建表、绝不自动补 fid——**处置是裁决不是工程默认**（补 fid 与建候选都影响
  段3/段4 的字段治理链，建候选后转正要走 Q13 字典管理员）；
- 报告只到"该补/该建候选/该人工判定"为止；
- `c7_runs` 是**执行留痕**，即便命中也**不回改**（append-only 口径），只报不改。

判定三类：

1. **黑户落库（阻断）**＝`g1_category_templates.field_list` 里出现 `'-'`、空串；
2. **悬空引用（阻断）**＝模板引用的 fid 在 `g2_fields` 里不存在，或已生效模板引用了非 active 字段；
3. **待登记（提示，不阻断）**＝`g2_field_candidates` 的 `pending_gate` 行数（Q13 转正队列），
   以及 `c7_runs` 历史留痕中的黑户条数（只报不改）。

退出码：无阻断项 ⇒ 0；有阻断项 ⇒ 1；目标库不是 Loom 迁移库（缺必需表／无 alembic_version）⇒ 2。

用法：
    python scripts/check_field_fid_registry.py [--json]
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
from app.product.modeling.models import C7Run, G1CategoryTemplate, G2FieldCandidate
from app.product.product_intake.models import G2Field

FORBIDDEN_FID = "-"  # 与 c7.py 的常量同源（Q68）
REQUIRED_TABLES = (
    G1CategoryTemplate.__table__,
    G2Field.__table__,
    C7Run.__table__,
    G2FieldCandidate.__table__,
)
LIVE_TEMPLATE_STATUSES = ("approved", "active")
SAMPLE_LIMIT = 20


def is_forbidden(value: object) -> bool:
    """黑户判定：非字符串、空串、空白串，以及 `'-'`（Q68 原文那个占位值）。"""
    return not isinstance(value, str) or value.strip() in ("", FORBIDDEN_FID)


async def is_migration_built(session) -> bool:
    """库是否经 `alembic upgrade head` 建出（同 check_master_data：否则"全零"会被读成"没回填"）。"""
    try:
        return bool((await session.execute(text("SELECT version_num FROM alembic_version"))).all())
    except SQLAlchemyError:
        return False


async def collect_facts(session) -> dict:
    """只读采集三处载体的事实（不判定、不写）。"""
    templates = (
        await session.execute(
            select(
                G1CategoryTemplate.category_id,
                G1CategoryTemplate.status,
                G1CategoryTemplate.field_list,
            )
        )
    ).all()
    fields = (await session.execute(select(G2Field.fid, G2Field.status))).all()
    runs = (
        await session.execute(
            select(C7Run.run_id, C7Run.layer, C7Run.field_list).where(C7Run.field_list.is_not(None))
        )
    ).all()
    candidates_pending = (
        await session.execute(
            select(func.count())
            .select_from(G2FieldCandidate)
            .where(G2FieldCandidate.status == "pending_gate")
        )
    ).scalar_one()
    return {
        "templates": templates,
        "fields": fields,
        "runs": runs,
        "candidates_pending": int(candidates_pending or 0),
    }


def evaluate(facts: dict) -> dict:
    """把采集到的事实判定成"字段治理链是否干净"（纯函数，无 DB 依赖）。"""
    field_status = {fid: status for fid, status in facts["fields"]}

    blacklisted: list[str] = []
    dangling: list[str] = []
    inactive_ref: list[str] = []
    checked_refs = 0

    for category_id, status, field_list in facts["templates"]:
        live = status in LIVE_TEMPLATE_STATUSES
        for raw in field_list or []:
            checked_refs += 1
            if is_forbidden(raw):
                blacklisted.append(
                    f"g1_category_templates[{category_id}]({status}).field_list 含黑户 {raw!r}"
                )
                continue
            fid = str(raw)
            known = field_status.get(fid)
            if known is None:
                dangling.append(f"g1_category_templates[{category_id}] 引用不存在的 fid {fid!r}")
            elif live and known != "active":
                inactive_ref.append(
                    f"g1_category_templates[{category_id}]({status}) 引用非 active 字段 "
                    f"{fid!r}（该字段 status={known}）"
                )

    trace_blacklist = [
        f"c7_runs[{run_id}] layer={layer} 历史留痕含黑户（只报不改）"
        for run_id, layer, field_list in facts["runs"]
        if any(is_forbidden(v) for v in (field_list or []))
    ]

    blocking = blacklisted + dangling
    return {
        "ok": not blocking,
        "blacklisted": blacklisted,
        "dangling": dangling,
        "inactive_ref": inactive_ref,
        "trace_blacklist": trace_blacklist,
        "counts": {
            "templates": len(facts["templates"]),
            "template_refs_checked": checked_refs,
            "g2_fields": len(facts["fields"]),
            "c7_runs_scanned": len(facts["runs"]),
            "candidates_pending": facts["candidates_pending"],
        },
    }


def render(report: dict) -> str:
    counts = report["counts"]
    lines = [
        "G2 字段 fid 上户口扫描（Q68，只读）",
        (
            f"  模板 {counts['templates']} 张 / 引用 {counts['template_refs_checked']} 处"
            f" / G2 字段 {counts['g2_fields']} 个 / c7_runs 留痕 {counts['c7_runs_scanned']} 条"
        ),
    ]
    for title, key in (
        ("黑户落库（阻断）", "blacklisted"),
        ("悬空引用（阻断）", "dangling"),
        ("引用非 active 字段（提示）", "inactive_ref"),
        ("历史留痕含黑户（只报不改）", "trace_blacklist"),
    ):
        items = report[key]
        shown = items[:SAMPLE_LIMIT]
        lines.append(f"  {title}：{len(items)}")
        lines.extend(f"    - {item}" for item in shown)
        if len(items) > len(shown):
            lines.append(f"    … 另有 {len(items) - len(shown)} 条未逐条列出")
    lines.append(f"  待转正候选（pending_gate，Q13）：{counts['candidates_pending']}")
    lines.append("结论：" + ("干净" if report["ok"] else "有阻断项，须按报告逐条处置"))
    return "\n".join(lines)


async def _table_names(session) -> set[str]:
    """目标库里已存在的表名集合（只查元数据，不建任何东西）。

    注意：`AsyncSession.run_sync` 传进来的是**同步 Session 而不是 Connection**，
    直接 `inspect(session)` 会抛 "No inspection system is available"——须经 `get_bind()`
    拿引擎再 inspect（与 check_master_data 的 `_sync` 同款，本条由真进程首跑暴露）。
    """

    def _sync(sync_session):
        return set(sqlalchemy_inspect(sync_session.get_bind()).get_table_names())

    return await session.run_sync(_sync)


async def missing_required_tables(session) -> list[str]:
    """返回目标库里**不存在**的必需表名（只查元数据，不建任何东西）。"""
    present = await _table_names(session)
    return [t.name for t in REQUIRED_TABLES if t.name not in present]


async def run(dsn: str, as_json: bool) -> int:
    engine = create_async_engine(dsn)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            missing = await missing_required_tables(session)
            if missing:
                print(f"目标库缺少必需表：{missing}（不是 Loom 迁移库）", file=sys.stderr)
                return 2
            if not await is_migration_built(session):
                print(
                    "目标库没有 alembic_version 行，不是 `alembic upgrade head` 建出的库",
                    file=sys.stderr,
                )
                return 2
            report = evaluate(await collect_facts(session))
    except SQLAlchemyError as exc:
        print(f"数据库不可用：{exc}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()
    print(json.dumps(report, ensure_ascii=False, indent=2) if as_json else render(report))
    return 0 if report["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G2 字段 fid 上户口扫描（Q68，只读）")
    parser.add_argument("--json", action="store_true", help="只输出 JSON（便于自动化解析）")
    parser.add_argument("--dsn", default=None, help="DB DSN（缺省取 LOOM_DATABASE_DSN / settings）")
    args = parser.parse_args(argv)
    dsn = args.dsn or get_settings().database_dsn
    return asyncio.run(run(dsn, args.json))


if __name__ == "__main__":
    raise SystemExit(main())
