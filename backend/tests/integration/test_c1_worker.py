"""C1 自动识别 worker 集成测试。

验证：ai_recognizing intake 被自动识别为 pending_review 候选；已有 pending 候选时
第二轮跳过，不重复消耗模型调用。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.model_registry.c1_worker import run_c1_once
from app.core.model_registry.models import (
    AIModel,
    AISceneRoute,
    SkillPrompt,
    SkillPromptVersion,
)
from app.core.model_registry.seeds import (
    CAT_RECOG_PROMPT_ID,
    CAT_RECOG_PROMPT_TEMPLATE,
    CAT_RECOG_PROMPT_VARIABLES,
    CAT_RECOG_PROMPT_VERSION,
    SCENE_CAT_RECOG,
    SYNTHETIC_MODEL_ID,
)
from app.core.skill7.models import SkillCandidate
from app.core.tenants.models import Tenant
from app.main import app
from app.product.modeling.models import C1IndustryThreshold, C1SignalWeight, G1Category
from app.product.product_intake.models import G2Field, ProductIntakeApplication
from tests.integration.staff_tokens import bearer, issue_write_token

CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


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
                AISceneRoute(scene=SCENE_CAT_RECOG, model_id=SYNTHETIC_MODEL_ID),
                SkillPrompt(
                    skill_id=SCENE_CAT_RECOG,
                    current_version=CAT_RECOG_PROMPT_VERSION,
                ),
                SkillPromptVersion(
                    version_id=CAT_RECOG_PROMPT_ID,
                    skill_id=SCENE_CAT_RECOG,
                    version=CAT_RECOG_PROMPT_VERSION,
                    template=CAT_RECOG_PROMPT_TEMPLATE,
                    variables={"vars": CAT_RECOG_PROMPT_VARIABLES},
                ),
                Tenant(tenant_id="t1", name="试点客户", plan="basic", status="active"),
                G2Field(fid="f_name", cat="common", field_name="产品名"),
                G2Field(fid="f_brief", cat="common", field_name="简介"),
                C1SignalWeight(signal="name", signal_name="产品名", enabled=True, weight=0.50),
                C1SignalWeight(signal="brief", signal_name="简介", enabled=True, weight=0.33),
                C1SignalWeight(signal="sellpoint", signal_name="卖点", enabled=True, weight=0.17),
                C1IndustryThreshold(
                    industry="general",
                    keywords=[],
                    threshold=0.85,
                    sensitive=False,
                    is_default=True,
                ),
                G1Category(name="护肤面霜", status="active"),
                G1Category(name="护肤乳液", status="active"),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers.update(bearer(await issue_write_token(c)))
        yield c


async def _make_ai_intake(client) -> str:
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "合成面霜", "f_brief": "保湿修护"}},
    )
    assert r.status_code == 201, r.text
    intake_id = r.json()["intake_id"]
    r = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "submit", "actor": CUSTOMER},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ai_recognizing"
    return intake_id


async def _candidate_count(session_factory) -> int:
    async with session_factory() as session:
        return (
            await session.scalars(select(func.count()).select_from(SkillCandidate))
        ).one()


async def test_c1_worker_does_not_retry_after_human_rejection(client, session_factory):
    intake_id = await _make_ai_intake(client)

    report = await run_c1_once(session_factory)
    assert report["processed"] == 1, report
    candidate_id = report["runs"][intake_id]["candidate_ids"][0]

    r = await client.post(
        f"/api/skill-candidates/{candidate_id}/decision",
        json={
            "decision": "rejected",
            "reason": "人工判定识别结果不可用",
            "actor": {"id": "ops-1", "roles": ["operations"]},
        },
    )
    assert r.status_code == 200, r.text

    async with session_factory() as session:
        cand = await session.get(SkillCandidate, candidate_id)
        assert cand.state == "archived"

    report2 = await run_c1_once(session_factory)
    assert report2["processed"] == 0, report2
    assert report2["skipped"] == 1, report2
    assert await _candidate_count(session_factory) == 1


async def test_c1_worker_processes_and_skips_existing_candidate(client, session_factory):
    intake_id = await _make_ai_intake(client)

    report = await run_c1_once(session_factory)
    assert report["processed"] == 1, report
    assert report["runs"][intake_id]["candidate_ids"]
    assert await _candidate_count(session_factory) == 1

    async with session_factory() as session:
        cand = (
            await session.scalars(
                select(SkillCandidate).where(SkillCandidate.intake_id == intake_id)
            )
        ).one()
        assert cand.state == "pending_review"
        assert cand.target_type == "c1_recognition"
        intake = await session.get(ProductIntakeApplication, intake_id)
        assert intake.status == "ai_recognizing"

    report2 = await run_c1_once(session_factory)
    assert report2["processed"] == 0, report2
    assert report2["skipped"] == 1, report2
    assert await _candidate_count(session_factory) == 1
