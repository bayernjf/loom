"""Q210 主数据回填自检器测试：纯判定逻辑（无 DB）＋ 采集层（sqlite 内存）。

纯函数 `evaluate` 不依赖数据库，覆盖"可发证 / 逐项缺失 / 平台不匹配 / goal 未激活 /
敏感领域零行"等分支；采集层用一个内存 sqlite 起五张表，走真实 insert → collect → evaluate。
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
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
    # 零行敏感领域：标记 sensitive_domains_zero，但仍可发证（Guard⑥ 默认放行）。
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
