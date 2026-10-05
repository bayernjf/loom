"""Q294（段8 PT-PCP-V1.5「动态信号每周更新触发重算」V2 第一切片）集成测试。

甲案口径（负责人「按你推荐来」＝3.1 甲 + 3.2 甲；设计见
docs/design-v2-pcp-weekly-recalc.md，裁决登记 02 C1.236）：
- 触发＝第六个 sweep 作业 `pcp_weekly_recalc_scan`（复用 SweepScheduler 300s tick、
  Q89 leader 锁、Q139 协作中止、Q151 PG fence），env 门控
  `LOOM_PCP_WEEKLY_SCAN_ENABLED` 默认关（关时空转返回 0）；
- 产出＝只开/续 `pcp_weekly_recalc` OpsTodo 提醒（assignee=operations），
  **不生成权重、不建候选、不写回 pcp_weight_tables**（AI 只产候选、人工 Gate 裁决；
  事件→权重映射规则原文未给，禁臆造）；
- 周节奏＝配置中心 `platform.recalc_weekday`(0)/`_hour`(2)/`_tz_offset_hours`(8)
  （默认＝周一 02:00 Asia/Shanghai，热更）；窗口＝上一锚点之后、本锚点及之前新生效的
  active 事件；无新事件的周跳过（待裁点 3 推荐口径）。

create_all 不跑迁移种子，周节奏默认值由 seeds.py 经 knob() 回落提供。
"""

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.config_center.cache import config_cache
from app.core.db import Base
from app.core.models import AuditLog
from app.core.sla.jobs import job_pcp_weekly_recalc_scan
from app.main import app  # noqa: F401  (注册全部模型元数据，供 create_all)
from app.platform.platform_adaptation.models import (
    PcpRecalcCandidate,
    PcpWeightTable,
    PlatformDynamicEvent,
)
from app.platform.platform_adaptation.service import (
    RECALC_TODO_ACTION,
    TODO_TYPE_PCP_WEEKLY_RECALC,
)
from app.product.modeling.models import OpsTodo

# 周一 11:00（Asia/Shanghai）⇒ 本地本周锚点 = 周一 02:00+08 = 2026-10-04 18:00Z，
# 上一锚点（窗口起点）= 2026-09-27 18:00Z。
NOW = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)
ANCHOR = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)
CYCLE_START = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)
DUE_DAYS = 7

_WEIGHTS = {f"f{i}": 1 / 17 for i in range(17)}


def _inst(value: datetime) -> datetime:
    """读回值按时刻比较：SQLite 丢偏移读回 naive（server_default 两侧都记 UTC）。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _event(
    event_id: str,
    platform: str,
    effective_start: datetime,
    *,
    status: str = "active",
) -> PlatformDynamicEvent:
    return PlatformDynamicEvent(
        event_id=event_id,
        platform=platform,
        event_type="算法调整",
        severity="high",
        effective_start=effective_start,
        status=status,
    )


def _pcp(pcp_id: str, product_space_id: str, platform: str) -> PcpWeightTable:
    return PcpWeightTable(
        pcp_id=pcp_id,
        tenant_id="t1",
        product_space_id=product_space_id,
        platform=platform,
        weights=dict(_WEIGHTS),
        status="active",
    )


def _todo(
    todo_id: str,
    pcp_id: str,
    *,
    status: str = "open",
    created_at: datetime | None = None,
) -> OpsTodo:
    return OpsTodo(
        todo_id=todo_id,
        tenant_id="t1",
        todo_type=TODO_TYPE_PCP_WEEKLY_RECALC,
        entity_type="pcp_weight_table",
        entity_id=pcp_id,
        status=status,
        assignee_role="operations",
        detail={"pcp_id": pcp_id},
        due_at=NOW + timedelta(days=DUE_DAYS),
        created_at=created_at,
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


async def _todos(session_factory) -> list[OpsTodo]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(OpsTodo).where(
                        OpsTodo.todo_type == TODO_TYPE_PCP_WEEKLY_RECALC
                    )
                )
            ).all()
        )


async def _reminder_audits(session_factory) -> list[AuditLog]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == RECALC_TODO_ACTION)
                )
            ).all()
        )


async def _candidate_count(session_factory) -> int:
    async with session_factory() as session:
        return int(
            await session.scalar(select(func.count()).select_from(PcpRecalcCandidate))
        )


async def _weights(session_factory, pcp_id: str) -> dict:
    async with session_factory() as session:
        pcp = await session.get(PcpWeightTable, pcp_id)
        return pcp.weights


def _douyin_rows() -> list:
    """douyin 平台两条 active PCP（不同产品空间）+ 一条窗口内新生效事件。"""
    return [
        _event("e-in-window", "douyin", datetime(2026, 9, 30, 4, 0, tzinfo=UTC)),
        _pcp("pcp-dy", "ps-1", "douyin"),
        _pcp("pcp-dy-2", "ps-2", "douyin"),
    ]


async def _run(session_factory, now: datetime = NOW) -> int:
    async with session_factory() as session:
        changed = await job_pcp_weekly_recalc_scan(session, now)
        await session.commit()
    return changed


async def test_gate_off_by_default_reminds_nothing(session_factory, monkeypatch):
    """门控默认关：窗口内事件原样放着，作业返回 0（V1 sweep 行为一字不变）。"""
    assert get_settings().pcp_weekly_scan_enabled is False
    await _seed(session_factory, *_douyin_rows())

    assert await _run(session_factory) == 0

    assert await _todos(session_factory) == []
    assert await _reminder_audits(session_factory) == []
    assert await _candidate_count(session_factory) == 0


async def test_new_events_in_window_open_reminders_with_audit(
    session_factory, monkeypatch
):
    """窗口内新生效事件 → 对应 active PCP 各开一条提醒（含审计、runner 语义、红线）。"""
    monkeypatch.setattr(get_settings(), "pcp_weekly_scan_enabled", True)
    await _seed(session_factory, *_douyin_rows())
    before = await _weights(session_factory, "pcp-dy")

    assert await _run(session_factory) == 2

    todos = sorted(await _todos(session_factory), key=lambda t: t.entity_id)
    assert [t.entity_id for t in todos] == ["pcp-dy", "pcp-dy-2"]
    for todo in todos:
        assert todo.status == "open"
        assert todo.assignee_role == "operations"
        assert todo.tenant_id == "t1"
        assert _inst(todo.due_at) == NOW + timedelta(days=DUE_DAYS)
        assert todo.detail["platform"] == "douyin"
        assert todo.detail["event_ids"] == ["e-in-window"]
        assert todo.detail["event_count"] == 1
        assert todo.detail["cycle_start"] == CYCLE_START.isoformat()
        assert todo.detail["anchor"] == ANCHOR.isoformat()
        assert todo.detail["renewed"] is False
        assert "不自动改权重" in todo.detail["next_step"]

    logs = await _reminder_audits(session_factory)
    assert len(logs) == 2
    # 系统作业口径（actor 为空）同 Q187/Q49：非自报人员身份。
    assert {log.actor_id for log in logs} == {None}
    assert {log.actor_roles for log in logs} == {None}
    assert {log.entity_id for log in logs} == {"pcp-dy", "pcp-dy-2"}

    # 红线：只提醒。不建候选、不碰权重。
    assert await _candidate_count(session_factory) == 0
    assert await _weights(session_factory, "pcp-dy") == before


async def test_pending_candidate_is_not_disturbed(session_factory, monkeypatch):
    """已有在途（pending）重算候选的 PCP 不再打扰——提醒不得与人工 Gate 叠加。"""
    monkeypatch.setattr(get_settings(), "pcp_weekly_scan_enabled", True)
    await _seed(
        session_factory,
        *_douyin_rows(),
        PcpRecalcCandidate(
            candidate_id="cand-1",
            pcp_id="pcp-dy",
            tenant_id="t1",
            product_space_id="ps-1",
            platform="douyin",
            source="manual",
            proposed_weights=dict(_WEIGHTS),
            change_list=[],
            status="pending",
        ),
    )

    assert await _run(session_factory) == 1
    assert [t.entity_id for t in await _todos(session_factory)] == ["pcp-dy-2"]


async def test_open_reminder_is_renewed_not_duplicated(session_factory, monkeypatch):
    """同周期内已有开放提醒 ⇒ 续期（刷新命中事件 + 顺延 due_at），不另开新条。"""
    monkeypatch.setattr(get_settings(), "pcp_weekly_scan_enabled", True)
    await _seed(session_factory, *_douyin_rows())

    assert await _run(session_factory) == 2
    # 同一周期内稍后一个 tick（周一 12:00+08，锚点不变）。
    later = NOW + timedelta(hours=1)
    assert await _run(session_factory, later) == 2

    todos = await _todos(session_factory)
    assert len(todos) == 2
    for todo in todos:
        assert todo.detail["renewed"] is True
        assert _inst(todo.due_at) == later + timedelta(days=DUE_DAYS)
        assert todo.detail["event_ids"] == ["e-in-window"]


async def test_resolved_reminder_is_not_repeated_within_the_same_cycle(
    session_factory, monkeypatch
):
    """本周期内已提醒过（含已 resolved）⇒ 不再重复打扰（运营自己关掉的不复活）。"""
    monkeypatch.setattr(get_settings(), "pcp_weekly_scan_enabled", True)
    await _seed(session_factory, *_douyin_rows())
    assert await _run(session_factory) == 2
    async with session_factory() as session:
        for todo in (await session.scalars(select(OpsTodo))).all():
            todo.status = "resolved"
            todo.resolution = "handled"
        await session.commit()

    assert await _run(session_factory) == 0
    assert len(await _todos(session_factory)) == 2
    assert all(t.status == "resolved" for t in await _todos(session_factory))


async def test_unresolved_reminder_from_previous_cycle_is_renewed(
    session_factory, monkeypatch
):
    """上一周期就挂着没处理的提醒 ⇒ 跨周期续期（1 条），不叠加成 2 条。"""
    monkeypatch.setattr(get_settings(), "pcp_weekly_scan_enabled", True)
    await _seed(
        session_factory,
        *_douyin_rows(),
        _todo(
            "todo-stale",
            "pcp-dy",
            status="escalated",
            created_at=NOW - timedelta(days=10),
        ),
    )

    assert await _run(session_factory) == 2

    todos = sorted(await _todos(session_factory), key=lambda t: t.entity_id)
    assert [t.entity_id for t in todos] == ["pcp-dy", "pcp-dy-2"]
    stale = todos[0]
    assert stale.todo_id == "todo-stale"
    assert stale.status == "escalated"
    assert stale.detail["renewed"] is True
    assert stale.detail["event_ids"] == ["e-in-window"]
    assert _inst(stale.due_at) == NOW + timedelta(days=DUE_DAYS)


async def test_resolved_reminder_from_previous_cycle_gets_a_new_one(
    session_factory, monkeypatch
):
    """上一周期已 resolved ＋ 本周期有新事件 ⇒ 开新提醒（旧条留史，两条并存）。"""
    monkeypatch.setattr(get_settings(), "pcp_weekly_scan_enabled", True)
    await _seed(
        session_factory,
        _event("e-in-window", "douyin", datetime(2026, 9, 30, 4, 0, tzinfo=UTC)),
        _pcp("pcp-dy", "ps-1", "douyin"),
        _todo(
            "todo-old",
            "pcp-dy",
            status="resolved",
            created_at=NOW - timedelta(days=10),
        ),
    )

    assert await _run(session_factory) == 1
    todos = await _todos(session_factory)
    assert len(todos) == 2
    assert sorted(t.status for t in todos) == ["open", "resolved"]
    assert [t.todo_id for t in todos if t.status == "open"] != ["todo-old"]


async def test_weeks_without_new_events_are_skipped(session_factory, monkeypatch):
    """无新事件的周跳过：窗口外（上一锚点前/本锚点后）与 archived 事件都不触发。"""
    monkeypatch.setattr(get_settings(), "pcp_weekly_scan_enabled", True)
    await _seed(
        session_factory,
        # 窗口起点前 1 分钟：上一周期的事，本周不重复提醒。
        _event("e-before-cycle", "douyin", CYCLE_START - timedelta(minutes=1)),
        # 本锚点之后才生效：下周才该提醒。
        _event("e-after-anchor", "douyin", ANCHOR + timedelta(hours=6)),
        # 窗口内但已归档。
        _event(
            "e-archived",
            "douyin",
            datetime(2026, 9, 29, 4, 0, tzinfo=UTC),
            status="archived",
        ),
        _pcp("pcp-dy", "ps-1", "douyin"),
    )

    assert await _run(session_factory) == 0
    assert await _todos(session_factory) == []
    assert await _reminder_audits(session_factory) == []


async def test_cadence_knobs_are_hot_updatable_and_shift_the_window(
    session_factory, monkeypatch
):
    """周节奏走配置中心热更：同一 now 改 hour=12 ⇒ 锚点回落一周、窗口跟着变。"""
    monkeypatch.setattr(get_settings(), "pcp_weekly_scan_enabled", True)
    await _seed(
        session_factory,
        # 周一 09-22 04:00Z：默认窗口外；hour=12 时（锚点 09-28 04:00Z）落进窗口。
        _event("e-early", "douyin", datetime(2026, 9, 22, 4, 0, tzinfo=UTC)),
        _pcp("pcp-dy", "ps-1", "douyin"),
    )
    assert await _run(session_factory) == 0

    config_cache.apply({"platform.recalc_hour": 12})
    assert await _run(session_factory) == 1

    todos = await _todos(session_factory)
    assert len(todos) == 1
    assert todos[0].detail["event_ids"] == ["e-early"]
    assert todos[0].detail["anchor"] == datetime(
        2026, 9, 28, 4, 0, tzinfo=UTC
    ).isoformat()


async def test_weekly_anchor_is_stable_across_ticks_inside_one_cycle(
    session_factory, monkeypatch
):
    """同一周期内任意 tick 得到同一锚点：锚点前（周一 01:00+08）回退到上一周期。"""
    monkeypatch.setattr(get_settings(), "pcp_weekly_scan_enabled", True)
    await _seed(
        session_factory,
        _event("e-in-window", "douyin", datetime(2026, 9, 30, 4, 0, tzinfo=UTC)),
        _event("e-prev-cycle", "douyin", datetime(2026, 9, 22, 4, 0, tzinfo=UTC)),
        _pcp("pcp-dy", "ps-1", "douyin"),
    )
    # 周一 01:00+08 ＝ 2026-10-04 17:00Z，本周钟点未到 ⇒ 锚点退回上一周一 02:00+08。
    before_anchor = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
    assert await _run(session_factory, before_anchor) == 1

    todos = await _todos(session_factory)
    assert len(todos) == 1
    assert todos[0].detail["event_ids"] == ["e-prev-cycle"]
    assert todos[0].detail["anchor"] == datetime(
        2026, 9, 27, 18, 0, tzinfo=UTC
    ).isoformat()
