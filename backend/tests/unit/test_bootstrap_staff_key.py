"""P1-2 引导脚本：门控关或库空时能签首令牌；已引导则拒绝，除非 --force。"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.models import AuditLog
from app.core.staff_auth import service
from app.core.staff_auth.models import StaffApiKey
from scripts.bootstrap_staff_key import BootstrapRefused, bootstrap_staff_key


async def _create_schema(dsn: str) -> None:
    engine = create_async_engine(dsn)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _rows(dsn: str) -> list[StaffApiKey]:
    engine = create_async_engine(dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            return list((await session.scalars(select(StaffApiKey))).all())
    finally:
        await engine.dispose()


@pytest.fixture
def dsn(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'staff.db'}"


async def test_bootstrap_works_while_gate_is_off(dsn):
    await _create_schema(dsn)
    row, plaintext = await bootstrap_staff_key(
        dsn=dsn,
        staff_id="ops-01",
        staff_name="运营",
        roles=["platform_admin"],
        gate_enabled=False,
    )

    # 明文只在这里出现一次，库里只留哈希与前缀。
    assert plaintext.startswith("loom_staff_")
    assert row.status == "active"
    assert row.key_hash != plaintext
    assert row.key_prefix == plaintext[:12]
    rows = await _rows(dsn)
    assert [r.key_id for r in rows] == [row.key_id]

    engine = create_async_engine(dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            assert await service.verify_staff_key(session, plaintext) is not None
            audits = await session.scalar(
                select(func.count()).select_from(AuditLog).where(
                    AuditLog.action == "staff_api_key.issue"
                )
            )
            assert audits == 1
    finally:
        await engine.dispose()


async def test_bootstrap_works_when_gate_is_on_but_table_is_empty(dsn):
    # 这正是后端因「门控开 + 库空」起不来的状态；脚本要能在不改配置的情况下救场。
    await _create_schema(dsn)
    row, plaintext = await bootstrap_staff_key(
        dsn=dsn,
        staff_id="ops-02",
        staff_name="运营2",
        roles=["platform_admin"],
        gate_enabled=True,
    )
    assert row.status == "active"
    assert plaintext.startswith("loom_staff_")


async def test_bootstrap_refuses_when_already_bootstrapped(dsn):
    await _create_schema(dsn)
    await bootstrap_staff_key(
        dsn=dsn,
        staff_id="ops-01",
        staff_name="运营",
        roles=["platform_admin"],
        gate_enabled=True,
    )
    with pytest.raises(BootstrapRefused) as info:
        await bootstrap_staff_key(
            dsn=dsn,
            staff_id="ops-03",
            staff_name="运营3",
            roles=["platform_admin"],
            gate_enabled=True,
        )
    # 拒绝要能照着做下一步，而不是只说一句 failed。
    assert "POST /api/admin/staff-keys" in str(info.value)
    assert "--force" in str(info.value)
    assert len(await _rows(dsn)) == 1


async def test_bootstrap_force_adds_a_second_key(dsn):
    await _create_schema(dsn)
    await bootstrap_staff_key(
        dsn=dsn,
        staff_id="ops-01",
        staff_name="运营",
        roles=["platform_admin"],
        gate_enabled=True,
    )
    row, _ = await bootstrap_staff_key(
        dsn=dsn,
        staff_id="ops-03",
        staff_name="运营3",
        roles=["operations"],
        gate_enabled=True,
        force=True,
    )
    assert row.staff_id == "ops-03"
    assert len(await _rows(dsn)) == 2
