"""Q210 生态：主数据 seed 模板的守卫与演示路径测试。

不验证业务数据（哨兵值不能落库），只验证：① 未改完的 CONFIG 被哨兵拦下；
② --demo 用示例假值能插库并让自检器判为「可发证」。
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import seed_master_data_template as seed_tpl


def test_unedited_config_is_flagged():
    bad = seed_tpl._is_unedited(seed_tpl.CONFIG)
    assert bad, "出厂 CONFIG 应被哨兵识别为未改完"
    assert "PLATFORM" in bad
    assert "GOAL_CODE" in bad


def test_demo_cfg_has_no_sentinels():
    assert seed_tpl._is_unedited(seed_tpl._demo_cfg()) == []


def test_demo_seed_self_checks_ready(capsys):
    seed_tpl.sys.argv = ["seed_master_data_template.py", "--demo"]
    rc = seed_tpl.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "已可发证" in out
    assert "Guard⑥" in out  # cp_law_sensitive_domains 零行提示也存在


# ---------------------------------------------------- Q222 复评查出的模板缺陷回归


def _engine():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    # 真 PG 上 --dsn 路径会撞已播种行（EDUCATION 目的码、medical 敏感领域）；
    # 这里用同一内存引擎（StaticPool 保证一个连接＝一个库）复现该状态。
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    return eng, async_sessionmaker(eng, expire_on_commit=False)


async def _prepare(collide: bool):
    from app.decision.compliance_center.models import CpLawSensitiveDomain
    from app.product.condition.models import ContentGoal

    eng, sf = _engine()
    await seed_tpl._create_tables_for_demo(eng)
    if collide:
        async with sf() as s:
            s.add(ContentGoal(code="EDUCATION", status="active"))
            s.add(CpLawSensitiveDomain(domain_id="d1", code="medical", name="医疗健康", status="active"))
            await s.commit()
    return eng, sf, ContentGoal, CpLawSensitiveDomain


def test_seed_skips_rows_that_already_exist():
    """目的码／敏感领域码已存在 ⇒ 跳过并说明，而不是抛 UniqueViolation。"""
    import asyncio

    async def go():
        eng, sf, ContentGoal, Domain = await _prepare(collide=True)
        try:
            cfg = seed_tpl._demo_cfg()  # GOAL_CODE 就是 EDUCATION，且库里已有
            cfg["SENSITIVE_DOMAINS"] = [{"code": "MEDICAL", "name": "医疗健康"}]  # 折大小写后同码
            async with sf() as s:
                outcome = await seed_tpl.seed(s, seed_tpl.build_rows(cfg))
            async with sf() as s2:
                goals = (await s2.execute(_select_count(ContentGoal))).scalar()
                domains = (await s2.execute(_select_count(Domain))).scalar()
            return outcome, goals, domains
        finally:
            await eng.dispose()

    outcome, goals, domains = asyncio.run(go())
    assert len(outcome["skipped"]) == 2, outcome
    assert goals == 1 and domains == 1, "跳过而非重复插：两张表各自仍只有一行"


def test_seed_still_inserts_when_nothing_collides():
    """正向对照：不冲突时照旧写入——否则上一条用例可能只是"什么都没干"。"""
    import asyncio

    from app.decision.compliance_center.models import CpLawSensitiveDomain
    from app.product.condition.models import ContentGoal

    async def go():
        eng, sf, _, _ = await _prepare(collide=False)
        try:
            cfg = seed_tpl._demo_cfg()
            cfg["GOAL_CODE"] = "BRAND-NEW-GOAL"
            cfg["CSP_PAYLOAD"] = dict(cfg["CSP_PAYLOAD"], goal="BRAND-NEW-GOAL")
            cfg["SENSITIVE_DOMAINS"] = [{"code": "tattoo", "name": "文身"}]
            async with sf() as s:
                outcome = await seed_tpl.seed(s, seed_tpl.build_rows(cfg))
            async with sf() as s2:
                goals = (await s2.execute(_select_count(ContentGoal))).scalar()
                domains = (await s2.execute(_select_count(CpLawSensitiveDomain))).scalar()
            return outcome, goals, domains
        finally:
            await eng.dispose()

    outcome, goals, domains = asyncio.run(go())
    assert outcome["skipped"] == [], outcome
    assert goals == 1 and domains == 1, "正向对照必须真的插进去，否则跳过逻辑可以是永远为真的空断言"


def _select_count(model):
    from sqlalchemy import func, select

    return select(func.count()).select_from(model)


def test_real_path_refuses_a_database_without_the_migrated_schema():
    """真实库路径不再代建表：缺表 ⇒ SchemaMissing（main 里转 exit 2）。"""
    import asyncio

    async def go():
        eng, sf = _engine()  # 有引擎、零表
        try:
            async with sf() as s:
                await seed_tpl._assert_real_schema(s)
        finally:
            await eng.dispose()

    try:
        asyncio.run(go())
        raise AssertionError("空库应被拒绝，而不是被建表")
    except seed_tpl.SchemaMissing as exc:
        assert "alembic upgrade head" in str(exc)
