"""Q210 主数据回填自检器测试：纯判定逻辑（无 DB）＋ 采集层（sqlite 内存）。

纯函数 `evaluate` 不依赖数据库，覆盖"可发证 / 逐项缺失 / 平台不匹配 / goal 未激活 /
敏感领域零行"等分支；采集层用一个内存 sqlite 起五张表，走真实 insert → collect → evaluate。
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.decision.layer_strategy.models import (
    KIND_CEP,
    KIND_CSP,
    KIND_CSTP,
    Package,
)
from app.platform.platform_adaptation.models import (
    PcpWeightTable,
    PublishSlot,
)
from app.product.condition.models import ContentGoal

# 脚本在 backend/scripts 下、不在包内，最后再 import。
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_master_data as cmd


def _facts(slots, pcps, packages, goals, sens=3):
    return {
        "slots": slots,
        "pcps": pcps,
        "packages": packages,
        "goals": goals,
        "sensitive_domains_count": sens,
    }


def _three_packages(ps, tenant, platform, goal):
    return [
        (ps, tenant, platform, goal, KIND_CSP),
        (ps, tenant, platform, goal, KIND_CSTP),
        (ps, tenant, platform, goal, KIND_CEP),
    ]


# --- 纯判定逻辑（无 DB）---


def test_ready_when_full_combo_present():
    facts = _facts(
        slots=[("slot-1", "wechat")],
        pcps=[("ps-1", "t-1", "wechat")],
        packages=_three_packages("ps-1", "t-1", "wechat", "EDUCATION"),
        goals=[("EDUCATION",)],
    )
    result = cmd.evaluate(facts)
    assert result["ready"] is True
    assert result["ready_combo"] == {
        "product_space_id": "ps-1",
        "tenant_id": "t-1",
        "platform": "wechat",
        "goal": "EDUCATION",
    }
    assert result["missing_required"] == []
    assert result["sensitive_domains_zero"] is False  # sens=3 默认非零


def test_not_ready_without_slot():
    facts = _facts(
        slots=[],
        pcps=[("ps-1", "t-1", "wechat")],
        packages=_three_packages("ps-1", "t-1", "wechat", "EDUCATION"),
        goals=[("EDUCATION",)],
    )
    result = cmd.evaluate(facts)
    assert result["ready"] is False
    assert any("publish_slots" in m for m in result["missing_required"])


def test_not_ready_without_pcp():
    facts = _facts(
        slots=[("slot-1", "wechat")],
        pcps=[],
        packages=_three_packages("ps-1", "t-1", "wechat", "EDUCATION"),
        goals=[("EDUCATION",)],
    )
    result = cmd.evaluate(facts)
    assert result["ready"] is False
    assert any("pcp_weight_tables" in m for m in result["missing_required"])


def test_not_ready_packages_present_but_platform_mismatch():
    # slot 平台 wechat，PCP 平台 douyin，三包也挂在 douyin 下 ⇒ resolver 会因
    # slot.platform 不符而失败（不看 gate，但平台必须匹配）。
    facts = _facts(
        slots=[("slot-1", "wechat")],
        pcps=[("ps-1", "t-1", "douyin")],
        packages=_three_packages("ps-1", "t-1", "douyin", "EDUCATION"),
        goals=[("EDUCATION",)],
    )
    result = cmd.evaluate(facts)
    assert result["ready"] is False
    assert result["ready_combo"] is None
    assert any("发布位" in g for g in result["gaps"])


def test_not_ready_packages_present_but_goal_not_active():
    # 三包挂在 goal=EDUCATION，但 active goals 只有 CONVERSION ⇒ 该组合不计入。
    facts = _facts(
        slots=[("slot-1", "wechat")],
        pcps=[("ps-1", "t-1", "wechat")],
        packages=_three_packages("ps-1", "t-1", "wechat", "EDUCATION"),
        goals=[("CONVERSION",)],
    )
    result = cmd.evaluate(facts)
    assert result["ready"] is False


def test_sensitive_domains_zero_flagged_separately():
    # 零行敏感领域：标记 sensitive_domains_zero，但仍可发证（注意这是**可配置态**——迁移 0007 自带 6 个 active 领域）。
    facts = _facts(
        slots=[("slot-1", "wechat")],
        pcps=[("ps-1", "t-1", "wechat")],
        packages=_three_packages("ps-1", "t-1", "wechat", "EDUCATION"),
        goals=[("EDUCATION",)],
        sens=0,
    )
    result = cmd.evaluate(facts)
    assert result["ready"] is True
    assert result["sensitive_domains_zero"] is True


# --- 采集层（sqlite 内存，真实 insert → collect → evaluate）---


def _seed_and_run():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=cmd._REQUIRED_TABLES)
    asyncio.run(_create())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _seed():
        async with session_factory() as s:
            s.add(PublishSlot(
                slot_id=str(uuid.uuid4()), platform="wechat", code="SLOT-1",
                name="测试位", slot_type="short_video", status="active",
            ))
            s.add(PcpWeightTable(
                pcp_id=str(uuid.uuid4()), tenant_id="t-1",
                product_space_id="ps-1", platform="wechat",
                weights={"a": 1.0}, status="active",
            ))
            s.add(ContentGoal(code="EDUCATION", status="active"))
            for kind in (KIND_CSP, KIND_CSTP, KIND_CEP):
                s.add(Package(
                    tenant_id="t-1", product_space_id="ps-1", platform="wechat",
                    goal="EDUCATION", kind=kind, payload={"k": "v"},
                    status="active",
                ))
            await s.commit()

    asyncio.run(_seed())
    return engine, session_factory


def test_collect_and_evaluate_ready_on_seeded_db():
    engine, session_factory = _seed_and_run()
    async def _run():
        async with session_factory() as s:
            facts = await cmd.collect_facts(s)
        return cmd.evaluate(facts)
    result = asyncio.run(_run())
    asyncio.run(engine.dispose())
    assert result["ready"] is True
    assert result["counts"]["publish_slots_active"] == 1
    assert result["counts"]["packages_active"] == 3
    # Q230：迁移 0042 起已种 6 个最小类目；本夹具走 create_all（不含迁移种子），故如实报 0。
    assert result["counts"]["g1_categories_active"] == 0


def test_collect_reports_not_ready_when_a_package_missing():
    engine, session_factory = _seed_and_run()
    # 删掉 CEP 包 ⇒ 三包不齐 ⇒ 不可发证。
    async def _remove():
        async with session_factory() as s:
            row = (
                await s.execute(
                    select(Package).where(Package.kind == KIND_CEP)
                )
            ).scalar_one()
            await s.delete(row)
            await s.commit()
    asyncio.run(_remove())

    async def _run():
        async with session_factory() as s:
            facts = await cmd.collect_facts(s)
        return cmd.evaluate(facts)
    result = asyncio.run(_run())
    asyncio.run(engine.dispose())
    assert result["ready"] is False
    assert result["counts"]["packages_active"] == 2


def test_main_json_output_is_machine_parseable(capsys, tmp_path):
    # main() 走 --json 时输出可被 json.loads 解析，且 ready 时退出码 0。
    # 用文件型 DSN：main() 内部会自建 engine，内存库无法跨引擎共享。
    db_file = tmp_path / "master_data.sqlite"
    dsn = f"sqlite+aiosqlite:///{db_file}"
    engine = create_async_engine(dsn)
    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=cmd._REQUIRED_TABLES)
    asyncio.run(_create())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async def _seed():
        async with session_factory() as s:
            s.add(PublishSlot(
                slot_id=str(uuid.uuid4()), platform="wechat", code="SLOT-1",
                name="测试位", slot_type="short_video", status="active",
            ))
            s.add(PcpWeightTable(
                pcp_id=str(uuid.uuid4()), tenant_id="t-1",
                product_space_id="ps-1", platform="wechat",
                weights={"a": 1.0}, status="active",
            ))
            s.add(ContentGoal(code="EDUCATION", status="active"))
            for kind in (KIND_CSP, KIND_CSTP, KIND_CEP):
                s.add(Package(
                    tenant_id="t-1", product_space_id="ps-1", platform="wechat",
                    goal="EDUCATION", kind=kind, payload={"k": "v"},
                    status="active",
                ))
            await s.commit()
    asyncio.run(_seed())
    asyncio.run(engine.dispose())

    sys.argv = ["check_master_data.py", "--json", "--dsn", dsn]
    rc = cmd.main()
    captured = capsys.readouterr().out
    parsed = json.loads(captured)
    assert parsed["ready"] is True
    assert rc == 0


def test_main_exits_1_when_not_ready(capsys, tmp_path):
    # 证伪：主数据零行（全新库默认态）时 self-checker 必须 exit 1，
    # 否则"可发证"判定形同虚设、永远绿。
    db_file = tmp_path / "empty.sqlite"
    dsn = f"sqlite+aiosqlite:///{db_file}"
    engine = create_async_engine(dsn)
    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=cmd._REQUIRED_TABLES)
    asyncio.run(_create())
    asyncio.run(engine.dispose())

    sys.argv = ["check_master_data.py", "--json", "--dsn", dsn]
    rc = cmd.main()
    captured = capsys.readouterr().out
    parsed = json.loads(captured)
    assert parsed["ready"] is False
    assert parsed["missing_required"], "缺项应为非空"
    assert rc == 1


# --- Q218：建库方式与只读性（这两条把 Q217 复评踩过的坑钉住）---


def test_evaluate_assumes_migration_built_by_default():
    """既有调用方不传 migration_built ⇒ 视为迁移库，不产生噪声告警。"""
    result = cmd.evaluate(_facts([("slot-1", "wechat")], [("ps-1", "t-1", "wechat")],
                                 _three_packages("ps-1", "t-1", "wechat", "EDUCATION"),
                                 [("EDUCATION",)]))
    assert result["migration_built"] is True
    assert result["warnings"] == []


def test_evaluate_warns_when_db_is_not_migration_built():
    """非迁移库的『全零』是建库方式造成的，必须显式说出来，不能伪装成业务未回填。"""
    facts = _facts([], [], [], [])
    facts["migration_built"] = False
    result = cmd.evaluate(facts)
    assert result["migration_built"] is False
    assert any("alembic_version" in w for w in result["warnings"])


def test_zero_sensitive_domains_on_a_migrated_db_is_flagged_as_deviation():
    """迁移自带 6 个 active 敏感领域 ⇒ 迁移库里数到 0 说明字典被动过，而不是『默认放行』。"""
    result = cmd.evaluate(_facts([("slot-1", "wechat")], [("ps-1", "t-1", "wechat")],
                                 _three_packages("ps-1", "t-1", "wechat", "EDUCATION"),
                                 [("EDUCATION",)], sens=0))
    assert result["ready"] is True  # 不影响可发证判定
    assert any("0007" in w for w in result["warnings"])
    assert "与迁移 0007 的 6 个种子不符" in cmd._format_report(result)


def test_g1_categories_zero_is_advisory_not_a_blocker():
    """Q229：G1 类目字典为空 ⇒ 段2 CAT-RECOG 候选集合为空（真模型会 502），
    但发证不需要 G1 类目，故**不影响「可发证」判定**，只作提示。"""
    facts = _facts([("slot-1", "wechat")], [("ps-1", "t-1", "wechat")],
                   _three_packages("ps-1", "t-1", "wechat", "EDUCATION"),
                   [("EDUCATION",)])
    facts["g1_categories_active"] = 0
    result = cmd.evaluate(facts)
    assert result["ready"] is True  # 不因类目为空而判不可发证
    assert result["g1_categories_zero"] is True
    assert result["counts"]["g1_categories_active"] == 0
    assert "g1_categories(active)=0" in cmd._format_report(result)

    facts["g1_categories_active"] = 7
    result = cmd.evaluate(facts)
    assert result["g1_categories_zero"] is False
    assert "g1_categories(active)=7" in cmd._format_report(result)


def test_is_migration_built_follows_the_alembic_version_row():
    async def _go():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            without = await cmd.is_migration_built(s)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=cmd._REQUIRED_TABLES)
            await conn.exec_driver_sql(
                "CREATE TABLE alembic_version (version_num VARCHAR(128) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
            await conn.exec_driver_sql(
                "INSERT INTO alembic_version (version_num) VALUES ('0041_discard_retention_seed')"
            )
        async with factory() as s:
            with_row = await cmd.is_migration_built(s)
        await engine.dispose()
        return without, with_row

    without, with_row = asyncio.run(_go())
    assert without is False and with_row is True


def test_tool_does_not_create_schema_and_exits_2_on_a_non_loom_db(tmp_path, capsys, monkeypatch):
    """只读承诺＋退出码 2：空库既不补表，也要与『未回填』（1）区分开。"""
    db = tmp_path / "empty.db"
    dsn = f"sqlite+aiosqlite:///{db}"
    before = _table_names(dsn)
    monkeypatch.setattr(sys, "argv", ["check_master_data.py", "--dsn", dsn])
    code = cmd.main()
    out = capsys.readouterr().out
    assert code == 2
    assert "不是经 `alembic upgrade head` 建出的" in out
    after = _table_names(dsn)
    assert after == before == set()  # 一个表都没被造出来
    # 正向对照：同一套计数方式必须能"看得见"表，否则上面的空集断言是空断言。
    from sqlalchemy import create_engine as _ce

    eng = _ce(dsn.replace("+aiosqlite", ""))
    Base.metadata.create_all(eng, tables=cmd._REQUIRED_TABLES)
    eng.dispose()
    assert len(_table_names(dsn)) == len(cmd._REQUIRED_TABLES)


def _table_names(dsn: str) -> set[str]:
    sync_dsn = dsn.replace("+aiosqlite", "")
    eng = create_engine(sync_dsn)
    try:
        return set(sa_inspect(eng).get_table_names())
    finally:
        eng.dispose()
