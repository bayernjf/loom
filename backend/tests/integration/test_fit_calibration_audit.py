"""fit_score 人工校准闭环的审计留痕（Q299，design-v2-fit-score-selflearning §3.2 乙）。

本切片是「人工校准」，不是「自学习」：端点形状不变（仍是 PUT publish-slots /
PUT fit-weights），只把四维静态分与目的权重矩阵的 before/after 钉进既有审计族
（slot.update / fit_weights.put），使每次校准可追溯；不新增写口、不自动触发
下游重算（fit_score 是发证时现算的派生值）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from tests.integration.staff_tokens import bearer, issue_write_token

OPS = {"id": "ops-1", "roles": ["operations"]}

SLOT = {
    "platform": "x_platform",
    "code": "X-CAL-01",
    "name": "X 校准发布位",
    "slot_type": "main",
    "chars_max": 280,
    "traffic": 80,
    "safe": 50,
    "conv": 40,
    "load": 100,
    "source_url": "https://example.com/rules",
}


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    app.dependency_overrides[get_auth_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async with session_factory() as session:
        session.add_all([ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


async def _latest_audit(session_factory, action: str) -> AuditLog:
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
            )
        ).all()
        assert rows, f"no audit for action={action}"
        return rows[-1]


async def test_slot_dimension_calibration_records_before_after(client, session_factory):
    created = await client.post("/api/admin/publish-slots", json={"item": SLOT, "actor": OPS})
    assert created.status_code == 201, created.text
    slot_id = created.json()["slot_id"]

    # 只校准四维里的两维（traffic 80→60、safe 50→70），其余不动。
    calibrated = {**SLOT, "traffic": 60, "safe": 70}
    resp = await client.put(
        f"/api/admin/publish-slots/{slot_id}",
        json={"item": calibrated, "actor": OPS},
    )
    assert resp.status_code == 200, resp.text

    audit = await _latest_audit(session_factory, "slot.update")
    assert audit.detail["fit_dim_changes"] == {
        "traffic": {"before": 80.0, "after": 60.0},
        "safe": {"before": 50.0, "after": 70.0},
    }


async def test_slot_update_without_dimension_change_has_empty_diff(client, session_factory):
    created = await client.post("/api/admin/publish-slots", json={"item": SLOT, "actor": OPS})
    slot_id = created.json()["slot_id"]

    # 四维原样、只改名字 ⇒ 校准差异为空，审计仍在但不伪造变化。
    renamed = {**SLOT, "name": "改名发布位"}
    resp = await client.put(
        f"/api/admin/publish-slots/{slot_id}",
        json={"item": renamed, "actor": OPS},
    )
    assert resp.status_code == 200, resp.text

    audit = await _latest_audit(session_factory, "slot.update")
    assert audit.detail["fit_dim_changes"] == {}


async def test_fit_weights_calibration_records_before_after(client, session_factory):
    # TRUST 首次无矩阵（新建，before=None）。
    first = await client.put(
        "/api/admin/fit-weights",
        json={
            "goal": "TRUST",
            "weights": {"traffic": 0.25, "safe": 0.25, "conv": 0.25, "load": 0.25},
            "actor": OPS,
        },
    )
    assert first.status_code == 200, first.text
    audit_new = await _latest_audit(session_factory, "fit_weights.put")
    assert audit_new.detail["weights_before"] is None
    assert audit_new.detail["weights"]["safe"] == 0.25

    # 再次校准（提高 safe 权重、总和仍为 1）。
    second = await client.put(
        "/api/admin/fit-weights",
        json={
            "goal": "TRUST",
            "weights": {"traffic": 0.15, "safe": 0.35, "conv": 0.25, "load": 0.25},
            "actor": OPS,
        },
    )
    assert second.status_code == 200, second.text
    audit_update = await _latest_audit(session_factory, "fit_weights.put")
    assert audit_update.detail["weights_before"] == {
        "traffic": 0.25,
        "safe": 0.25,
        "conv": 0.25,
        "load": 0.25,
    }
    assert audit_update.detail["weights"]["safe"] == 0.35
