"""PLATFORM-ADAPTER 只读预览口集成测试（Q296 甲，design-v2-platform-adapter-business §3.1）。

覆盖：三料组料（frozen PWS／Q36 规则命中／生效动态事件）→ 经模型网关调
PLATFORM-ADAPTER 场景（V1 路由 synthetic）→ 四态机械映射（allow／block／
downgrade／pending_review）、五键契约（missing 分支在消费方归一，decision/gate
为 None 不造假）、快照不存在 404、无令牌 401、**全程零副作用**（不写审计、
不落 SkillRun、不建候选、不触 final_content_whitelists——PT 约束 4/6）。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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
from app.core.skill7.models import SkillRun
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from app.platform.platform_adaptation.models import (
    PlatformDynamicEvent,
    PlatformRule,
)
from app.product.whitelist_center.models import PwsSnapshot
from tests.integration.staff_tokens import bearer, issue_write_token

PREVIEW_PATH = "/api/admin/platform-adapter/preview"
_NOW = datetime.now(tz=UTC)


def _pws(pws_id: str, *, status: str, active: bool, version: str) -> PwsSnapshot:
    return PwsSnapshot(
        pws_id=pws_id,
        tenant_id="t-e2e-preview",
        product_space_id="ps-preview",
        version=version,
        status=status,
        is_active=active,
        fingerprint="a" * 64,
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
                _pws("pws-stale", status="superseded", active=False, version="v1.0"),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


async def _counts(session_factory) -> tuple[int, int, int]:
    async with session_factory() as session:
        audit = len((await session.scalars(select(AuditLog))).all())
        runs = len((await session.scalars(select(SkillRun))).all())
    return audit, runs, 0


async def _preview(client, pws_id: str = "pws-frozen", **overrides) -> dict:
    payload = {
        "pws_snapshot_id": pws_id,
        "platform": "x_platform",
        "slot_type": "short_video",
    }
    payload.update(overrides)
    resp = await client.post(PREVIEW_PATH, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_unknown_snapshot_is_404(client):
    resp = await client.post(
        PREVIEW_PATH,
        json={"pws_snapshot_id": "nope", "platform": "x_platform", "slot_type": "short_video"},
    )
    assert resp.status_code == 404


async def test_preview_without_token_is_401(session_factory):
    """只读口也走已验真身份闸（Q242 同族）：无令牌 401，自报角色不认。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            PREVIEW_PATH,
            json={"pws_snapshot_id": "pws-frozen", "platform": "x_platform", "slot_type": "short_video"},
        )
    assert resp.status_code == 401


async def test_allow_is_read_only_and_five_keys(client, session_factory):
    """无阻断规则、无动态事件 → allow；五键齐；全程零副作用（无审计、无 SkillRun）。"""
    before = await _counts(session_factory)
    body = await _preview(client)
    after = await _counts(session_factory)

    assert before == after, (before, after)
    assert body["pws"]["frozen"] is True and body["pws"]["pws_id"] == "pws-frozen"
    assert body["platform_rules"] == {"effect": None, "matched_rule_ids": []}
    assert body["dynamic_events"] == []
    adapter = body["adapter"]
    assert adapter == {
        "missing": False,
        "decision": "allow",
        "reason": "no blocking rules or dynamic signals",
        "refs": [],
        "gate": "pending_review",
    }
    assert body["previewed_by"]


async def test_block_on_blocked_rule(client, session_factory):
    async with session_factory() as session:
        session.add(
            PlatformRule(
                rule_id="rule-blocked",
                selector_level="platform",
                platform="x_platform",
                slot_type=None,
                slot_id=None,
                country=None,
                effect="blocked",
            )
        )
        await session.commit()
    body = await _preview(client)
    assert body["adapter"]["decision"] == "block"
    assert body["adapter"]["reason"] == "platform rule effect=blocked"
    assert body["adapter"]["refs"] == ["rule:rule-blocked"]


async def test_downgrade_on_partial_rule(client, session_factory):
    async with session_factory() as session:
        session.add(
            PlatformRule(
                rule_id="rule-partial",
                selector_level="platform",
                platform="x_platform",
                slot_type=None,
                slot_id=None,
                country=None,
                effect="partial",
            )
        )
        await session.commit()
    body = await _preview(client)
    assert body["adapter"]["decision"] == "downgrade"
    assert body["adapter"]["refs"] == ["rule:rule-partial"]
    assert body["platform_rules"]["effect"] == "partial"


async def test_pending_review_on_active_dynamic_event(client, session_factory):
    async with session_factory() as session:
        session.add(
            PlatformDynamicEvent(
                platform="x_platform",
                event_type="algorithm_change",
                severity="high",
                effective_start=_NOW - timedelta(hours=1),
                effective_end=_NOW + timedelta(days=3),
                status="active",
            )
        )
        await session.commit()
    body = await _preview(client)
    assert body["adapter"]["decision"] == "pending_review"
    assert body["adapter"]["reason"] == "active dynamic signal requires human review"
    assert len(body["dynamic_events"]) == 1


async def test_missing_branch_is_normalized_to_five_keys(client):
    """快照非 frozen：协议内缺失形状在消费方归一为五键，decision/gate 为 None 不造假。"""
    body = await _preview(client, pws_id="pws-stale")
    adapter = body["adapter"]
    assert adapter["missing"] is True
    assert adapter["reason"] == "no_frozen_pws"
    assert set(adapter) == {"missing", "decision", "reason", "refs", "gate"}
    assert adapter["decision"] is None and adapter["gate"] is None and adapter["refs"] == []


async def test_blocked_rule_wins_over_events(client, session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                PlatformRule(
                    rule_id="rule-blocked",
                    selector_level="platform",
                    platform="x_platform",
                    slot_type=None,
                    slot_id=None,
                    country=None,
                    effect="blocked",
                ),
                PlatformDynamicEvent(
                    platform="x_platform",
                    event_type="algorithm_change",
                    severity="high",
                    effective_start=_NOW - timedelta(hours=1),
                    effective_end=None,
                    status="active",
                ),
            ]
        )
        await session.commit()
    body = await _preview(client)
    assert body["adapter"]["decision"] == "block"
    assert body["adapter"]["refs"] == ["rule:rule-blocked"]
