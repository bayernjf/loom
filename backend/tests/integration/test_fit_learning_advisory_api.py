"""Q352 集成测试：fit_score 自学习 advisory 接线（GET /api/admin/publish-slots/{id}/fit-score）。

这一段守的是「能力有、面也够得着」——`fit_learning.py` 自 Q325 起就是全仓零生产调用点的
纯函数（02 C1.268 把它记成已落地，实则没人消费）。本批把它接进 fit-score 读面，于是这些
用例逐条钉死接线形状：

- 门控关（默认）→ `learning` 恒 null，人工四维与聚合口径一字不变；
- 门控开 → 回带 advisory 建议，traffic/conv/load 由窗口内 matched 效果记录算出，
  `safe` 恒不在建议里；
- 收窄口径承重：别的发布位／别的目的／窗口外的记录一律不得混进来；
- 观察窗读的是配置中心键（改窗=改数据可见面，不是改码）；
- 稀疏纪律：未采集的键不得被显示成"学到 0 分"；
- 纯只读：不写审计、不改 `publish_slots` 静态分。

create_all 不跑迁移种子，发布位/权重/成品/效果记录均由本文件 fixture 自插。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_READY, ContentProduct
from app.core.config import get_settings
from app.core.db import Base, get_session
from app.core.effects.models import STATUS_MATCHED, EffectRecord
from app.core.models import AuditLog
from app.main import app
from app.platform.platform_adaptation import service
from app.platform.platform_adaptation.models import GoalFitWeight, PublishSlot

PATH = "/api/admin/publish-slots/{slot_id}/fit-score"
# Q346（裁甲，02 C1.289）：fit-score 归入段7/8 那条 query 读闸。
ADMIN = {"actor_id": "ops-1", "roles": "operations"}

_NOW = datetime(2026, 10, 13, 4, 0, tzinfo=UTC)


def _at(days_ago: int) -> datetime:
    return _NOW - timedelta(days=days_ago)


def _record(content_id: str, *, day: int, metrics: dict) -> EffectRecord:
    return EffectRecord(
        source="agent",
        external_content_id=content_id,
        matched_content_id=content_id,
        tenant_id="t1",
        platform_post_id=f"https://x/{content_id}",
        captured_at=_at(day),
        metrics=metrics,
        status=STATUS_MATCHED,
        received_by="key-1",
    )


@pytest_asyncio.fixture
async def session_factory(monkeypatch):
    # 冻结"现在"，窗口边界才是可复现的断言而不是运行当天的运气。
    monkeypatch.setattr(service, "_now", lambda: _NOW)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                PublishSlot(
                    slot_id="slot-1",
                    platform="x_platform",
                    code="S-1",
                    name="测试发布位",
                    slot_type="short_video",
                    traffic=80,
                    safe=60,
                    conv=70,
                    load=50,
                ),
                # 有档案、无效果记录的发布位（"没数据"必须回 null，不是回一屏 0 分）。
                PublishSlot(
                    slot_id="slot-empty",
                    platform="x_platform",
                    code="S-2",
                    name="无效果的发布位",
                    slot_type="short_video",
                    traffic=10,
                    safe=10,
                    conv=10,
                    load=10,
                ),
                GoalFitWeight(
                    goal="ENGAGEMENT",
                    weights={"traffic": 0.4, "safe": 0.2, "conv": 0.2, "load": 0.2},
                ),
                # 同发布位、同目的的两个成品。
                ContentProduct(
                    content_id="c1", tenant_id="t1", product_space_id="ps-1",
                    final_id="fcw-1", goal="ENGAGEMENT", platform="x_platform",
                    slot_id="slot-1", status=CONTENT_READY,
                ),
                ContentProduct(
                    content_id="c2", tenant_id="t1", product_space_id="ps-1",
                    final_id="fcw-2", goal="ENGAGEMENT", platform="x_platform",
                    slot_id="slot-1", status=CONTENT_READY,
                ),
                # 反向对照两型：同目的不同位、同位不同目的。
                ContentProduct(
                    content_id="c3", tenant_id="t1", product_space_id="ps-1",
                    final_id="fcw-3", goal="ENGAGEMENT", platform="x_platform",
                    slot_id="slot-other", status=CONTENT_READY,
                ),
                ContentProduct(
                    content_id="c4", tenant_id="t1", product_space_id="ps-1",
                    final_id="fcw-4", goal="CONVERSION", platform="x_platform",
                    slot_id="slot-1", status=CONTENT_READY,
                ),
            ]
        )
        await session.commit()
        session.add_all(
            [
                # 窗口内（2 天前）：plays 20 万→traffic 截到 100，conv (100+100)/1000=20，
                # read_rate 两样本均值 (0.8+0.4)/2=0.6→load 60。
                _record("c1", day=2, metrics={"plays": 100_000, "likes": 5_000,
                                              "inquiries": 100, "read_rate": 0.8}),
                _record("c2", day=5, metrics={"plays": 100_000, "comments": 5_000,
                                              "conversions": 100, "read_rate": 0.4}),
                # 窗口外（400 天前）：数值再大也不得进建议。
                _record("c1", day=400, metrics={"plays": 9_000_000, "read_rate": 0.99}),
                # 别的发布位／别的目的：不得串入 slot-1×ENGAGEMENT。
                _record("c3", day=2, metrics={"plays": 8_000_000, "read_rate": 0.9}),
                _record("c4", day=2, metrics={"plays": 7_000_000, "read_rate": 0.9}),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _get(client, slot_id="slot-1", goal="ENGAGEMENT"):
    resp = await client.get(PATH.format(slot_id=slot_id), params={**ADMIN, "goal": goal})
    assert resp.status_code == 200
    return resp.json()


async def test_gate_off_by_default_learning_is_null(client):
    """默认门控关：learning=null，且既有人工分与 breakdown 一字不变。"""
    assert get_settings().fit_learning_enabled is False
    body = await _get(client)
    assert body["learning"] is None
    assert body["fit_score"] == 80 * 0.4 + 60 * 0.2 + 70 * 0.2 + 50 * 0.2
    assert [r["dim"] for r in body["breakdown"]] == ["traffic", "safe", "conv", "load"]


async def test_gate_on_returns_advisory_for_the_in_window_rows(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "fit_learning_enabled", True)
    body = await _get(client)
    learning = body["learning"]
    assert learning is not None
    # 只算窗口内 4 个样本之外的两行 matched（c1@2d、c2@5d）：
    # plays 合计 20 万 → traffic 100（截断）；inquiries+conversions=200 → conv 20.0；
    # read_rate 均值 0.6 → load 60.0。
    assert learning["scores"] == {"traffic": 100.0, "conv": 20.0, "load": 60.0}
    # safe 无效果指标可学，恒不在建议里（Q325 拍板）。
    assert "safe" not in learning["scores"]
    assert learning["sample_records"] == 2
    assert learning["sample_contents"] == 2
    assert learning["window_days"] == 90
    assert learning["truncated"] is False
    # advisory 不参与裁决：聚合分仍是人工四维算出来的。
    assert body["fit_score"] == 80 * 0.4 + 60 * 0.2 + 70 * 0.2 + 50 * 0.2


async def test_window_comes_from_the_config_center_knob(client, monkeypatch):
    """把窗口收到 3 天，400 天前的行仍排除、但 5 天前的行也一并出局（改窗=改可见面）。"""
    monkeypatch.setattr(get_settings(), "fit_learning_enabled", True)
    monkeypatch.setattr(service, "knob", lambda key: 3 if key == service.FIT_LEARNING_WINDOW_KEY else 90)
    body = await _get(client)
    learning = body["learning"]
    assert learning["window_days"] == 3
    # 只剩 c1@2d：plays 10 万→traffic 100、inquiries 100→conv 10.0、read_rate 0.8→load 80。
    assert learning["scores"] == {"traffic": 100.0, "conv": 10.0, "load": 80.0}
    assert learning["sample_records"] == 1
    assert learning["sample_contents"] == 1


async def test_no_in_window_data_means_no_suggestion_not_zero_scores(client, monkeypatch):
    """反向对照：换一个有档案、零效果记录的发布位→learning=null，而不是回一屏 0 分。"""
    monkeypatch.setattr(get_settings(), "fit_learning_enabled", True)
    body = await _get(client, slot_id="slot-empty")
    assert body["incomplete"] is False
    assert body["learning"] is None


async def test_sparse_source_key_is_not_scored(client, session_factory, monkeypatch):
    """只采到 inquiries 的记录：conv 有值、traffic/load 不进取值（未采集≠0）。"""
    async with session_factory() as session:
        session.add(
            ContentProduct(
                content_id="c5", tenant_id="t1", product_space_id="ps-1",
                final_id="fcw-5", goal="RETENTION", platform="x_platform",
                slot_id="slot-1", status=CONTENT_READY,
            )
        )
        session.add(_record("c5", day=3, metrics={"inquiries": 500}))
        await session.commit()
    monkeypatch.setattr(get_settings(), "fit_learning_enabled", True)
    body = await _get(client, goal="RETENTION")
    learning = body["learning"]
    assert learning is not None
    assert set(learning["scores"]) == {"conv"}
    assert learning["scores"]["conv"] == 50.0


async def test_advisory_is_read_only(client, session_factory, monkeypatch):
    """纯只读：不写审计、不改发布位静态分。"""
    monkeypatch.setattr(get_settings(), "fit_learning_enabled", True)

    async def snapshot() -> tuple[int, dict]:
        async with session_factory() as session:
            audits = len((await session.scalars(select(AuditLog))).all())
            slot = await session.get(PublishSlot, "slot-1")
            dims = {dim: getattr(slot, dim) for dim in ("traffic", "safe", "conv", "load")}
        return audits, dims

    before = await snapshot()
    body = await _get(client)
    assert body["learning"] is not None
    assert await snapshot() == before


def test_the_window_key_is_a_registered_knob():
    """接线锁：服务读的键名必须在配置中心注册（改名会让 knob() 当场 KeyError）。"""
    from app.core.config_center.seeds import SEED_BY_KEY

    assert service.FIT_LEARNING_WINDOW_KEY == "platform.fit_learning_window_days"
    row = SEED_BY_KEY[service.FIT_LEARNING_WINDOW_KEY]
    assert row[1] == "platform" and row[2] == "int" and row[3] == 90
    assert row[5] == {"min": 1, "max": 365}
