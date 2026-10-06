"""PLATFORM-ADAPTER 候选 + HumanGate 集成测试（Q300，design-v2-platform-adapter §3.2 乙）。

红线：approve 只解除 pending 并留痕——不改平台规则/发布位、不产 final_id、
不影响 FCW；四态是 advisory。候选由运营显式触发、经 Q296 同一组料 + synthetic
网关机械生成；同一 (pws, platform, slot_type, slot_id) 仅一条 pending。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.model_registry.models import AIModel, AISceneRoute, SkillPrompt, SkillPromptVersion
from app.core.model_registry.seeds import (
    PLATFORM_ADAPTER_PROMPT_ID,
    PLATFORM_ADAPTER_PROMPT_TEMPLATE,
    PLATFORM_ADAPTER_PROMPT_VARIABLES,
    PLATFORM_ADAPTER_PROMPT_VERSION,
    SCENE_PLATFORM_ADAPTER,
    SYNTHETIC_MODEL_ID,
)
from app.core.models import AuditLog
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from app.platform.platform_adaptation.models import PlatformAdapterCandidate
from app.product.whitelist_center.models import PwsSnapshot
from tests.integration.staff_tokens import acting_as, bearer, issue_write_token


def _pws(pws_id: str, *, status: str, active: bool, version: str) -> PwsSnapshot:
    return PwsSnapshot(
        pws_id=pws_id,
        tenant_id="t-e2e-adapter",
        product_space_id="ps-adapter",
        version=version,
        status=status,
        is_active=active,
        fingerprint="b" * 64,
        snapshot={},
        readiness={"all_green": True},
    )


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
        session.add_all(
            [
                AIModel(
                    model_id=SYNTHETIC_MODEL_ID,
                    model_code="synthetic-deterministic",
                    provider="synthetic",
                    status="active",
                ),
                AISceneRoute(scene=SCENE_PLATFORM_ADAPTER, model_id=SYNTHETIC_MODEL_ID),
                SkillPrompt(
                    skill_id=SCENE_PLATFORM_ADAPTER,
                    current_version=PLATFORM_ADAPTER_PROMPT_VERSION,
                ),
                SkillPromptVersion(
                    version_id=PLATFORM_ADAPTER_PROMPT_ID,
                    skill_id=SCENE_PLATFORM_ADAPTER,
                    version=PLATFORM_ADAPTER_PROMPT_VERSION,
                    template=PLATFORM_ADAPTER_PROMPT_TEMPLATE,
                    variables={"vars": PLATFORM_ADAPTER_PROMPT_VARIABLES},
                ),
                _pws("pws-frozen", status="frozen", active=True, version="v2.0"),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


PAYLOAD = {
    "pws_snapshot_id": "pws-frozen",
    "platform": "x_platform",
    "slot_type": "short_video",
    "actor": {"id": "ops-1", "roles": ["operations"]},
}


async def _create(client, **overrides) -> dict:
    resp = await client.post(
        "/api/admin/platform-adapter/candidates", json={**PAYLOAD, **overrides}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_persists_synthetic_pending_candidate(client, session_factory):
    body = await _create(client)
    assert body["status"] == "pending"
    assert body["source"] == "synthetic"
    assert body["decision"] == "allow"
    assert body["missing"] is False
    async with session_factory() as session:
        count = (
            await session.scalar(
                select(func.count()).select_from(PlatformAdapterCandidate)
            )
        )
        assert count == 1
        audit = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "platform_adapter.candidate_created"
                )
            )
        ).one()
        assert audit.detail["decision"] == "allow"


async def test_duplicate_pending_is_409_then_new_after_resolution(client):
    first = await _create(client)
    dup = await client.post("/api/admin/platform-adapter/candidates", json=PAYLOAD)
    assert dup.status_code == 409

    approved = await client.post(
        f"/api/admin/platform-adapter/candidates/{first['candidate_id']}/approve",
        json={"actor": {"id": "ops-1", "roles": ["operations"]}},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    # 上一条已裁决 ⇒ 同键可再提一条 pending（partial unique 只约束 pending）。
    second = await _create(client)
    assert second["status"] == "pending"
    assert second["candidate_id"] != first["candidate_id"]


async def test_approve_is_advisory_and_writes_audit(client, session_factory):
    body = await _create(client)
    resp = await client.post(
        f"/api/admin/platform-adapter/candidates/{body['candidate_id']}/approve",
        json={"actor": {"id": "ops-1", "roles": ["operations"]}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["approved_by"]

    async with session_factory() as session:
        audit = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "platform_adapter.approved")
            )
        ).one()
        assert audit.detail["decision"] == "allow"
        assert audit.detail["advisory_only"] is True
        assert audit.detail["_actor_via"] == "staff_token"


async def test_reject_requires_reason_and_records_it(client):
    body = await _create(client)
    no_reason = await client.post(
        f"/api/admin/platform-adapter/candidates/{body['candidate_id']}/reject",
        json={"reason": "", "actor": {"id": "ops-1", "roles": ["operations"]}},
    )
    assert no_reason.status_code == 422

    resp = await client.post(
        f"/api/admin/platform-adapter/candidates/{body['candidate_id']}/reject",
        json={"reason": "证据不足", "actor": {"id": "ops-1", "roles": ["operations"]}},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert resp.json()["rejected_reason"] == "证据不足"


async def test_approve_unknown_or_resolved_is_404(client):
    body = await _create(client)
    cid = body["candidate_id"]
    await client.post(
        f"/api/admin/platform-adapter/candidates/{cid}/reject",
        json={"reason": "x", "actor": {"id": "ops-1", "roles": ["operations"]}},
    )
    again = await client.post(
        f"/api/admin/platform-adapter/candidates/{cid}/approve",
        json={"actor": {"id": "ops-1", "roles": ["operations"]}},
    )
    assert again.status_code == 404
    missing = await client.post(
        "/api/admin/platform-adapter/candidates/nope/approve",
        json={"actor": {"id": "ops-1", "roles": ["operations"]}},
    )
    assert missing.status_code == 404


async def test_create_requires_operations_token(client):
    async with acting_as(client, ["product_reviewer"], staff_id="s-rev"):
        resp = await client.post(
            "/api/admin/platform-adapter/candidates",
            json={**PAYLOAD, "actor": {"id": "x", "roles": []}},
        )
    assert resp.status_code == 403


async def test_create_without_token_is_401(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/admin/platform-adapter/candidates", json=PAYLOAD)
    assert resp.status_code == 401


async def test_list_filters_by_status(client):
    body = await _create(client)
    await client.post(
        f"/api/admin/platform-adapter/candidates/{body['candidate_id']}/approve",
        json={"actor": {"id": "ops-1", "roles": ["operations"]}},
    )
    headers = {"actor_id": "ops-1", "roles": "operations"}
    pending = await client.get(
        "/api/admin/platform-adapter/candidates", params={"status": "pending", **headers}
    )
    approved = await client.get(
        "/api/admin/platform-adapter/candidates", params={"status": "approved", **headers}
    )
    assert pending.status_code == approved.status_code == 200
    assert pending.json() == []
    assert len(approved.json()) == 1
