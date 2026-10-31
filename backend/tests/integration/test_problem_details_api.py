"""统一错误响应契约测试（Tier0 评审 2026-10-30 H2 收口）。

- 未识别异常：全局 ``Exception`` handler 返回固定 RFC 9457 ProblemDetails
  形状（``{type, title, status, detail, instance}``），原文只进服务端日志。
- 上游/管道异常：router 层 502 只回固定泛化 detail，上游响应体/管道校验
  细节只进日志。
- 带错误码的业务错误（4xx 语义化 detail）形状零变化，不在本用例面内。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.model_registry import drivers
from app.core.model_registry.drivers import DriverError, GenerationResult
from app.core.model_registry.models import AIModel, AISceneRoute, SkillPrompt, SkillPromptVersion
from app.core.model_registry.seeds import (
    CAT_RECOG_PROMPT_ID,
    CAT_RECOG_PROMPT_TEMPLATE,
    CAT_RECOG_PROMPT_VARIABLES,
    CAT_RECOG_PROMPT_VERSION,
    SCENE_CAT_RECOG,
    SYNTHETIC_MODEL_ID,
)
from app.core.tenants.models import Tenant
from app.main import app
from app.product.modeling.models import C1IndustryThreshold, C1SignalWeight, G1Category
from app.product.product_intake import service as intake_service
from app.product.product_intake.models import G2Field

OPS = {"id": "ops-1", "roles": ["operations"]}

LEAK_TEXT = "SUPER-SECRET-UPSTREAM-BODY"


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session

    async with factory() as session:
        # 迁移 0014 的种子三行 + 指针（测试不跑迁移），CAT-RECOG 试点 C1 配置。
        session.add_all(
            [
                AIModel(
                    model_id=SYNTHETIC_MODEL_ID,
                    model_code="synthetic-deterministic",
                    provider="synthetic",
                    status="active",
                ),
                AISceneRoute(scene=SCENE_CAT_RECOG, model_id=SYNTHETIC_MODEL_ID),
                SkillPrompt(skill_id=SCENE_CAT_RECOG, current_version=CAT_RECOG_PROMPT_VERSION),
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
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


async def _submitted_intake(client: AsyncClient) -> str:
    r = await client.post(
        "/api/intakes",
        json={"tenant_id": "t1", "profile": {"f_name": "面霜", "f_brief": "保湿修护"}},
    )
    intake_id = r.json()["intake_id"]
    r = await client.post(
        f"/api/intakes/{intake_id}/transitions",
        json={"event": "submit", "actor": OPS},
    )
    assert r.status_code == 200, r.text
    return intake_id


async def test_upstream_pipeline_502_is_generic_and_logs_original(client, monkeypatch, caplog):
    """DriverError 的上游原文（响应体片段）不得进 502 响应体，只进日志。"""
    intake_id = await _submitted_intake(client)

    async def _broken(self, **kwargs):
        raise DriverError(f"LLM provider returned 500: {LEAK_TEXT}")

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _broken)
    with caplog.at_level("WARNING", logger="loom.errors"):
        r = await client.post(
            f"/api/intakes/{intake_id}/c1-recognition/llm-invoke", json={"actor": OPS}
        )
    assert r.status_code == 502
    body = r.json()
    assert body == {"detail": "upstream model pipeline failed"}
    raw = repr(body)
    assert LEAK_TEXT not in raw
    assert "LLM provider returned 500" not in raw
    assert LEAK_TEXT in caplog.text


async def test_malformed_model_output_502_is_generic(client, monkeypatch):
    """管道校验失败（OutputInvalid）仍是 502，detail 固定泛化、不回显模型输出。"""
    intake_id = await _submitted_intake(client)

    async def _ok(self, **kwargs):
        return GenerationResult(text="this is not json", input_tokens=3, output_tokens=4)

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _ok)
    r = await client.post(
        f"/api/intakes/{intake_id}/c1-recognition/llm-invoke", json={"actor": OPS}
    )
    # 管道校验失败仍是 502，detail 固定泛化（不再回显 "this is not json"）。
    assert r.status_code == 502
    assert r.json() == {"detail": "upstream model pipeline failed"}
    assert "not json" not in repr(r.json())


async def test_unhandled_exception_returns_problem_details(caplog, monkeypatch):
    """逃逸出路由的未知异常：500 ProblemDetails 固定形状，原文只进日志。"""
    leak = "ECONNREFUSED 10.0.0.5:5432 — relation intakes missing"

    async def _boom(*args, **kwargs):
        raise RuntimeError(leak)

    monkeypatch.setattr(intake_service, "list_intakes", _boom)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with caplog.at_level("ERROR", logger="loom.startup"):
            r = await ac.get("/api/intakes", params={"tenant_id": "t1"})
    assert r.status_code == 500
    assert r.json() == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "internal error",
        "instance": "/api/intakes",
    }
    raw = r.text
    assert "ECONNREFUSED" not in raw
    assert "relation intakes missing" not in raw
    assert leak in caplog.text
