"""Q68 G2 字段 fid 上户口扫描器测试：纯判定逻辑（无 DB）＋采集层（sqlite 内存）。

两个方向都钉：阻断项必须真判红（黑户 `'-'`／空串、引用不存在的 fid）；
提示项必须**不**阻断（非 active 字段引用、c7_runs 历史留痕、待转正候选）——
"提示被当成阻断"和"阻断漏检"同样是错。
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.product.modeling.models import C7Run, G1CategoryTemplate, G2FieldCandidate
from app.product.product_intake.models import G2Field

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_field_fid_registry as cmd

TABLES = (
    G1CategoryTemplate.__table__,
    G2Field.__table__,
    C7Run.__table__,
    G2FieldCandidate.__table__,
)


def _facts(templates=(), fields=(), runs=(), candidates_pending=0):
    return {
        "templates": list(templates),
        "fields": list(fields),
        "runs": list(runs),
        "candidates_pending": candidates_pending,
    }


# --- 纯判定逻辑（无 DB）---


def test_clean_templates_report_ok():
    report = cmd.evaluate(
        _facts(
            templates=[("cat-1", "approved", ["FLD-FREQ", "FLD-LIFT"])],
            fields=[("FLD-FREQ", "active"), ("FLD-LIFT", "active")],
        )
    )
    assert report["ok"] is True
    assert report["blacklisted"] == []
    assert report["dangling"] == []
    assert report["counts"]["template_refs_checked"] == 2


def test_dash_fid_is_blacklisted_and_blocks():
    report = cmd.evaluate(
        _facts(templates=[("cat-1", "approved", ["-"])], fields=[("FLD-FREQ", "active")])
    )
    assert report["ok"] is False
    assert any("黑户" in item for item in report["blacklisted"])


def test_empty_and_blank_fid_are_blacklisted():
    for bad in ("", "   ", None, 3):
        report = cmd.evaluate(_facts(templates=[("cat-1", "draft", [bad])], fields=[]))
        assert report["ok"] is False, bad
        assert report["blacklisted"], bad


def test_unknown_fid_is_dangling_and_blocks():
    report = cmd.evaluate(
        _facts(templates=[("cat-1", "approved", ["FLD-GONE"])], fields=[("FLD-A", "active")])
    )
    assert report["ok"] is False
    assert any("不存在" in item for item in report["dangling"])


def test_inactive_ref_is_hint_not_block():
    """提示项不许阻断：已生效模板引用 deprecated 字段要报，但 ok 仍为 True。"""
    report = cmd.evaluate(
        _facts(
            templates=[("cat-1", "approved", ["FLD-OLD"])],
            fields=[("FLD-OLD", "deprecated")],
        )
    )
    assert report["ok"] is True
    assert report["inactive_ref"] and "deprecated" in report["inactive_ref"][0]


def test_inactive_ref_on_draft_template_is_silent():
    report = cmd.evaluate(
        _facts(templates=[("cat-1", "draft", ["FLD-OLD"])], fields=[("FLD-OLD", "deprecated")])
    )
    assert report["inactive_ref"] == []


def test_c7_run_trace_reports_but_never_blocks():
    report = cmd.evaluate(
        _facts(
            templates=[("cat-1", "approved", ["FLD-A"])],
            fields=[("FLD-A", "active")],
            runs=[("run-1", 1, ["-"]), ("run-2", 2, ["FLD-A"])],
        )
    )
    assert report["ok"] is True
    assert len(report["trace_blacklist"]) == 1
    assert "run-1" in report["trace_blacklist"][0]


def test_pending_candidates_only_counted():
    report = cmd.evaluate(_facts(candidates_pending=7))
    assert report["ok"] is True
    assert report["counts"]["candidates_pending"] == 7


def test_render_mentions_every_bucket():
    report = cmd.evaluate(
        _facts(
            templates=[("cat-1", "approved", ["-"])],
            fields=[("FLD-A", "deprecated")],
            runs=[("run-1", 1, ["-"])],
            candidates_pending=2,
        )
    )
    rendered = cmd.render(report)
    for bucket in ("黑户落库", "悬空引用", "引用非 active 字段", "历史留痕含黑户", "pending_gate"):
        assert bucket in rendered
    assert "有阻断项" in rendered


# --- 采集层（sqlite 内存，真实 insert → collect → evaluate）---


async def _collect_roundtrip():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=TABLES)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add_all(
            [
                G2Field(fid="FLD-A", cat="common", field_name="A", status="active"),
                G2Field(fid="FLD-OLD", cat="common", field_name="OLD", status="deprecated"),
                G1CategoryTemplate(
                    category_id="cat-1", field_list=["FLD-A", "-"], status="approved"
                ),
                C7Run(
                    run_id=str(uuid.uuid4()),
                    tenant_id="t-1",
                    intake_id="int-1",
                    category_id="cat-1",
                    layer=1,
                    field_list=["-"],
                ),
                G2FieldCandidate(
                    field_name="新字段", source_layer="c7_layer4", status="pending_gate"
                ),
            ]
        )
        await session.commit()
        facts = await cmd.collect_facts(session)
    await engine.dispose()
    return facts


def test_collect_reads_real_rows():
    report = cmd.evaluate(asyncio.run(_collect_roundtrip()))
    assert report["ok"] is False
    assert report["blacklisted"] and report["trace_blacklist"]
    assert report["counts"] == {
        "templates": 1,
        "template_refs_checked": 2,
        "g2_fields": 2,
        "c7_runs_scanned": 1,
        "candidates_pending": 1,
    }


def test_is_forbidden_matches_c7_module_constant():
    """与写侧闸同源：脚本里的 FORBIDDEN_FID 必须等于 c7.py 那个（Q68 两个落点不许漂）。"""
    from app.product.modeling import c7

    assert cmd.FORBIDDEN_FID == c7.FORBIDDEN_FID == "-"


# --- 主流程（run）：表存在性判定与退出码 ---


async def _prepare_db(path: Path, *, with_alembic: bool, blacklisted: bool) -> str:
    dsn = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(dsn)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=TABLES)
        if with_alembic:
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
            await conn.execute(text("INSERT INTO alembic_version VALUES ('0059_video_generation_tasks')"))
        if blacklisted:
            await conn.execute(
                text(
                    "INSERT INTO g1_category_templates (category_id, field_list, status) "
                    "VALUES ('cat-1', '[\"-\"]', 'approved')"
                )
            )
        await conn.execute(
            text(
                "INSERT INTO g2_fields (fid, cat, field_name, status) VALUES ('FLD-A', 'common', 'A', 'active')"
            )
        )
    await engine.dispose()
    return dsn


def test_run_exits_1_on_blacklist(tmp_path, capsys):
    """黑户存在 ⇒ exit 1 且报告指名道姓（真进程首跑暴露过 inspector 绑定缺陷，这条一并锁住）。"""
    dsn = asyncio.run(_prepare_db(tmp_path / "dirty.db", with_alembic=True, blacklisted=True))
    assert asyncio.run(cmd.run(dsn, as_json=True)) == 1
    assert "黑户" in capsys.readouterr().out


def test_run_exits_0_on_clean_db(tmp_path, capsys):
    dsn = asyncio.run(_prepare_db(tmp_path / "clean.db", with_alembic=True, blacklisted=False))
    assert asyncio.run(cmd.run(dsn, as_json=False)) == 0
    assert "结论：干净" in capsys.readouterr().out


def test_run_exits_2_when_tables_missing(tmp_path, capsys):
    """不是 Loom 迁移库 ⇒ exit 2，且**不代建 schema**（只读纪律）。"""
    dsn = f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}"
    assert asyncio.run(cmd.run(dsn, as_json=True)) == 2
    assert "缺少必需表" in capsys.readouterr().err


def test_run_exits_2_without_alembic_row(tmp_path, capsys):
    """有表但没有 alembic_version 行 ⇒ 同样 exit 2（否则"全零"会被读成"业务没回填"）。"""
    dsn = asyncio.run(_prepare_db(tmp_path / "nover.db", with_alembic=False, blacklisted=False))
    assert asyncio.run(cmd.run(dsn, as_json=True)) == 2
    assert "alembic_version" in capsys.readouterr().err
