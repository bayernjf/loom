"""Q187（docs/20 §6.5 C4 收口）集成测试：discarded 成品保留期物理清理作业。

甲案口径（工程推荐、原文未给，标待负责人追认）：
- 保留窗口＝配置中心 `content.discard_retention_days`（默认 180，热更）；
- 归档目标＝物理删除 + 逐行 `content.discard_purged` 审计留痕；
- 索引处理＝不动 Q124 的 partial unique index（迁移 0032）；
- 破坏性动作 env 门控 `LOOM_DISCARD_PURGE_ENABLED` 默认关（同 Q87/Q137/Q161）；
- 有下游引用的行留档不删：effect_records/effect_claims 是硬 FK（Q126/Q127），
  import_jobs 是 payload 可重放的作业历史（Q161）。

create_all 不跑迁移种子，保留窗口默认值由 seeds.py 经 knob() 回落提供。
"""

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import (
    CONTENT_DISCARDED,
    CONTENT_READY,
    CONTENT_REJECTED,
    ContentProduct,
)
from app.content.service import PURGE_ACTION, purge_expired_discarded
from app.core.config import get_settings
from app.core.config_center.cache import config_cache
from app.core.db import Base
from app.core.effects.models import EffectClaim, EffectRecord
from app.core.imports.models import ImportJob
from app.core.models import AuditLog
from app.core.sla.jobs import job_discard_purge
from app.core.sla.runner import run_jobs

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
RETENTION_DAYS = 180


def _product(
    content_id: str,
    *,
    status: str = CONTENT_DISCARDED,
    age_days: int = RETENTION_DAYS + 20,
    final_id: str = "fcw-1",
    language: str = "zh-CN",
) -> ContentProduct:
    return ContentProduct(
        content_id=content_id,
        tenant_id="t1",
        product_space_id="ps-1",
        final_id=final_id,
        goal="种草",
        platform="douyin",
        kind="article",
        language=language,
        status=status,
        discard_reason="连续三版复检不过" if status == CONTENT_DISCARDED else None,
        updated_at=NOW - timedelta(days=age_days),
    )


def _effect(content_id: str, *, matched: bool = True) -> EffectRecord:
    return EffectRecord(
        source="customer-backfill",
        external_content_id=f"ext-{content_id}",
        matched_content_id=content_id if matched else None,
        tenant_id="t1" if matched else None,
        platform_post_id="https://example.test/post/1",
        captured_at=NOW - timedelta(days=1),
        status="matched" if matched else "orphan",
    )


def _import_job(job_id: str, content_id: str) -> ImportJob:
    return ImportJob(
        job_id=job_id,
        tenant_id="t1",
        content_id=content_id,
        format="csv",
        payload="external_content_id,platform_post_id\n",
        requested_by="cust-1",
    )


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    config_cache.invalidate()
    await engine.dispose()


async def _seed(session_factory, *rows) -> None:
    async with session_factory() as session:
        session.add_all(list(rows))
        await session.commit()


async def _statuses(session_factory) -> dict[str, str]:
    async with session_factory() as session:
        rows = (await session.scalars(select(ContentProduct))).all()
        return {r.content_id: r.status for r in rows}


async def _audit_actions(session_factory) -> list[AuditLog]:
    async with session_factory() as session:
        return list(
            (await session.scalars(select(AuditLog).where(AuditLog.action == PURGE_ACTION))).all()
        )


async def test_gate_off_by_default_purges_nothing(session_factory):
    """门控默认关：过期 discarded 行原样保留，作业返回 0（V1 行为不变）。"""
    await _seed(session_factory, _product("c-old"))
    assert get_settings().discard_purge_enabled is False

    async with session_factory() as session:
        assert await job_discard_purge(session, NOW) == 0
        await session.commit()

    assert await _statuses(session_factory) == {"c-old": CONTENT_DISCARDED}
    assert await _audit_actions(session_factory) == []


async def test_expired_discarded_purged_with_audit(session_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "discard_purge_enabled", True)
    await _seed(session_factory, _product("c-old"))

    async with session_factory() as session:
        assert await job_discard_purge(session, NOW) == 1
        await session.commit()

    assert await _statuses(session_factory) == {}
    logs = await _audit_actions(session_factory)
    assert len(logs) == 1
    assert logs[0].entity_id == "c-old"
    assert logs[0].entity_type == "content_product"
    assert logs[0].tenant_id == "t1"
    assert logs[0].actor_id is None and logs[0].actor_roles is None
    assert logs[0].detail["final_id"] == "fcw-1"
    assert logs[0].detail["language"] == "zh-CN"
    assert logs[0].detail["kind"] == "article"
    assert logs[0].detail["discard_reason"] == "连续三版复检不过"
    assert logs[0].detail["retention_days"] == RETENTION_DAYS
    assert logs[0].detail["discarded_at"]


async def test_row_within_retention_kept(session_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "discard_purge_enabled", True)
    await _seed(session_factory, _product("c-fresh", age_days=RETENTION_DAYS - 1))

    async with session_factory() as session:
        assert await purge_expired_discarded(session, NOW, 200) == 0
        await session.commit()

    assert "c-fresh" in await _statuses(session_factory)


async def test_non_discarded_rows_never_purged(session_factory, monkeypatch):
    """只清 discarded 终态：rejected/ready 即使同样过期也不动。"""
    monkeypatch.setattr(get_settings(), "discard_purge_enabled", True)
    await _seed(
        session_factory,
        _product("c-rejected", status=CONTENT_REJECTED, final_id="fcw-r"),
        _product("c-ready", status=CONTENT_READY, final_id="fcw-y", language="en-US"),
    )

    async with session_factory() as session:
        assert await job_discard_purge(session, NOW) == 0
        await session.commit()

    assert await _statuses(session_factory) == {
        "c-rejected": CONTENT_REJECTED,
        "c-ready": CONTENT_READY,
    }


async def test_rows_referenced_by_effect_records_kept(session_factory, monkeypatch):
    """effect_records.matched_content_id 是硬 FK（Q126）：留档不删，段13 时序不断链。"""
    monkeypatch.setattr(get_settings(), "discard_purge_enabled", True)
    await _seed(session_factory, _product("c-eff"), _effect("c-eff"))

    async with session_factory() as session:
        assert await job_discard_purge(session, NOW) == 0
        await session.commit()

    assert "c-eff" in await _statuses(session_factory)


async def test_orphan_effect_records_do_not_block_purge(session_factory, monkeypatch):
    """孤儿行 matched_content_id 为空，不构成引用，不得挡住清理。"""
    monkeypatch.setattr(get_settings(), "discard_purge_enabled", True)
    await _seed(session_factory, _product("c-old"), _effect("c-old", matched=False))

    async with session_factory() as session:
        assert await job_discard_purge(session, NOW) == 1
        await session.commit()

    assert await _statuses(session_factory) == {}


async def test_rows_referenced_by_effect_claims_kept(session_factory, monkeypatch):
    """effect_claims.content_id 是硬 FK（Q127 认领映射）：留档不删。"""
    monkeypatch.setattr(get_settings(), "discard_purge_enabled", True)
    await _seed(
        session_factory,
        _product("c-claim"),
        EffectClaim(external_content_id="ext-claim", content_id="c-claim", claimed_by="ops-1"),
    )

    async with session_factory() as session:
        assert await job_discard_purge(session, NOW) == 0
        await session.commit()

    assert "c-claim" in await _statuses(session_factory)


async def test_rows_referenced_by_import_jobs_kept(session_factory, monkeypatch):
    """import_jobs.content_id 是 payload 可重放的作业历史（Q161）：留档不删。"""
    monkeypatch.setattr(get_settings(), "discard_purge_enabled", True)
    await _seed(session_factory, _product("c-import"), _import_job("job-1", "c-import"))

    async with session_factory() as session:
        assert await job_discard_purge(session, NOW) == 0
        await session.commit()

    assert "c-import" in await _statuses(session_factory)


async def test_batch_limit_oldest_first(session_factory, monkeypatch):
    """单轮批量上限（env 运维参数）：只清最老的 N 行，其余下轮再来。"""
    monkeypatch.setattr(get_settings(), "discard_purge_enabled", True)
    monkeypatch.setattr(get_settings(), "discard_purge_batch", 2)
    await _seed(
        session_factory,
        _product("c-300", age_days=300, final_id="fcw-a"),
        _product("c-250", age_days=250, final_id="fcw-b"),
        _product("c-200", age_days=200, final_id="fcw-c"),
    )

    async with session_factory() as session:
        assert await job_discard_purge(session, NOW) == 2
        await session.commit()

    assert await _statuses(session_factory) == {"c-200": CONTENT_DISCARDED}
    assert {log.entity_id for log in await _audit_actions(session_factory)} == {
        "c-300",
        "c-250",
    }


async def test_retention_window_hot_updatable(session_factory, monkeypatch):
    """保留窗口走配置中心（Q9 热更）：改缓存即改口径，不改码不重启。"""
    monkeypatch.setattr(get_settings(), "discard_purge_enabled", True)
    await _seed(session_factory, _product("c-10d", age_days=10))

    async with session_factory() as session:
        assert await purge_expired_discarded(session, NOW, 200) == 0

    config_cache.apply({"content.discard_retention_days": 5})
    async with session_factory() as session:
        assert await purge_expired_discarded(session, NOW, 200) == 1
        await session.commit()

    assert await _statuses(session_factory) == {}
    logs = await _audit_actions(session_factory)
    assert logs[0].detail["retention_days"] == 5


async def test_sweep_runner_reports_discard_purge(session_factory, monkeypatch):
    """作业已登记进统一 runner（第五作业），随定时 sweep 与手工 /run 同一路径跑。"""
    monkeypatch.setattr(get_settings(), "discard_purge_enabled", True)
    await _seed(session_factory, _product("c-old"))

    report = await run_jobs(session_factory, now=NOW, only=["discard_purge"])

    assert report == {"discard_purge": {"changed": 1}}
    assert await _statuses(session_factory) == {}
