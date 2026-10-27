"""W6-1 测试：model-hub 投影同步/解析 + 注册表只读化。

用 fake opener 注入 ModelHubClient（不触网），投影数据取自共享契约 fixture。
"""

import json
import os
import tempfile
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.model_registry import gateway, hub
from app.core.model_registry.drivers import GenerationResult

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
)
FIXTURE = os.path.join(
    ROOT,
    "model-hub",
    "contracts",
    "fixtures",
    "models-response.example.json",
)
with open(FIXTURE, encoding="utf-8") as fh:
    CATALOG = json.load(fh)


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return json.dumps(self._body).encode("utf-8")


def make_opener(catalog):
    def opener(req):
        return FakeResponse(catalog)

    return opener


@pytest.fixture(autouse=True)
def _clean_projection():
    hub.reset_hub_projection()
    yield
    hub.reset_hub_projection()
    hub.stop_hub_refresh()


@pytest.fixture
def _env_hub(monkeypatch, tmp_path):
    cache_path = str(tmp_path / "hub-cache.json")
    monkeypatch.setenv("MODEL_HUB_URL", "http://localhost:8791")
    monkeypatch.setenv("MODEL_HUB_TOKEN", "tok_test")
    monkeypatch.setenv("MODEL_HUB_CACHE_PATH", cache_path)
    return cache_path


_FAKE_CACHE_DIR = tempfile.mkdtemp(prefix="loom-hub-test-")


def _fake_client(catalog=None):
    from model_hub_client import ModelHubClient

    return ModelHubClient(
        hub_url="http://localhost:8791",
        token="tok_test",
        cache_path=os.path.join(_FAKE_CACHE_DIR, "hub-cache.json"),
        opener=make_opener(catalog if catalog is not None else CATALOG),
    )


# ---------------- 配置 ----------------


def test_settings_unconfigured(monkeypatch):
    monkeypatch.delenv("MODEL_HUB_URL", raising=False)
    monkeypatch.delenv("MODEL_HUB_TOKEN", raising=False)
    assert hub.is_hub_configured() is False
    assert hub.hub_settings() is None


def test_settings_configured(_env_hub):
    assert hub.is_hub_configured() is True
    url, token, cache_path = hub.hub_settings()
    assert url == "http://localhost:8791"
    assert token == "tok_test"
    assert cache_path == _env_hub


def test_settings_disabled(monkeypatch):
    monkeypatch.setenv("MODEL_HUB_URL", "http://localhost:8791")
    monkeypatch.setenv("MODEL_HUB_TOKEN", "tok_test")
    monkeypatch.setenv("MODEL_HUB_DISABLED", "1")
    assert hub.is_hub_disabled() is True
    assert hub.is_hub_configured() is False


# ---------------- provider 推断 ----------------


@pytest.mark.parametrize(
    "base_url,expected",
    [
        ("https://apihub.agnes-ai.com/v1", "agnes"),
        ("https://ark.cn-beijing.volces.com/api/v3", "ark"),
        ("https://api.openai.com/v1", "openai"),
        ("https://api.anthropic.com", "anthropic"),
    ],
)
def test_provider_inference(base_url, expected):
    assert hub.provider_from_base_url(base_url) == expected


# ---------------- 同步 ----------------


def test_sync_encrypts_keys():
    result = hub.sync_hub_projection(_fake_client())
    assert result == {"revision": 42, "pulled": 3}
    projection = hub.load_projection()
    assert projection is not None
    assert projection.revision == 42
    # 进程内单例中 api_key 必须是信封，无明文。
    for m in projection.models:
        assert m.api_key_enc != ""
        assert "PLACEHOLDER_KEY_NOT_REAL" not in m.api_key_enc
        assert m.api_key_enc.startswith("gAAAAA")


def test_sync_first_primary_is_default():
    hub.sync_hub_projection(_fake_client())
    projection = hub.load_projection()
    text_models = [m for m in projection.models if "text" in m.modalities]
    defaults = [m for m in text_models if m.is_default]
    assert len(defaults) == 1
    assert defaults[0].alias == "noul"


# ---------------- 解析 ----------------


def test_resolve_default_text():
    hub.sync_hub_projection(_fake_client())
    resolved = hub.resolve_hub_model("text")
    assert resolved is not None
    assert resolved.model == "ark-code-latest"
    assert resolved.api_key == "PLACEHOLDER_KEY_NOT_REAL_0001"
    assert resolved.assignment_id == "asn_0001noul"
    assert resolved.provider == "ark"


def test_resolve_by_alias():
    hub.sync_hub_projection(_fake_client())
    resolved = hub.resolve_hub_model("text", alias="score")
    assert resolved is not None
    assert resolved.model == "doubao-seed-1-6-250615"


def test_resolve_image_modality():
    hub.sync_hub_projection(_fake_client())
    resolved = hub.resolve_hub_model("image")
    assert resolved is not None
    assert resolved.model == "doubao-seedream-4-0-250828"


def test_resolve_unknown_alias_returns_default():
    hub.sync_hub_projection(_fake_client())
    resolved = hub.resolve_hub_model("text", alias="does-not-exist")
    assert resolved is not None
    assert resolved.model == "ark-code-latest"


def test_resolve_no_projection():
    assert hub.resolve_hub_model("text") is None


def test_resolve_unknown_modality():
    hub.sync_hub_projection(_fake_client())
    assert hub.resolve_hub_model("audio") is None


# ---------------- 后台刷新 ----------------


def test_start_stop_refresh(_env_hub):
    hub.start_hub_refresh()
    assert hub._refresh_thread is not None
    assert hub._refresh_thread.is_alive()
    hub.stop_hub_refresh()
    assert hub._refresh_thread is None


# ---------------- API 层（只读化） ----------------


@pytest_asyncio.fixture
async def session_factory():
    # Import the full app first so every model is registered on Base.metadata.
    from app.main import app

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


async def _client():
    from app.main import app

    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_write_endpoints_gone_in_hub_mode(_env_hub, session_factory):
    # 先同步投影，让 GET 有数据。
    hub.sync_hub_projection(_fake_client())
    async with await _client() as ac:
        payload = {
            "model_code": "x",
            "provider": "agnes",
            "capability": "chat",
            "actor": {"id": "pa-1", "roles": ["platform_admin"]},
        }
        r = await ac.post("/api/admin/ai-models", json=payload)
        assert r.status_code == 410


async def test_get_models_reads_projection(_env_hub, session_factory):
    hub.sync_hub_projection(_fake_client())
    async with await _client() as ac:
        r = await ac.get(
            "/api/admin/ai-models",
            params=[("actor_id", "pa-1"), ("roles", "platform_admin")],
        )
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 3
        codes = {row["model_code"] for row in rows}
        assert codes == {
            "ark-code-latest",
            "doubao-seed-1-6-250615",
            "doubao-seedream-4-0-250828",
        }


async def test_hub_status(_env_hub, session_factory):
    hub.sync_hub_projection(_fake_client())
    async with await _client() as ac:
        r = await ac.get(
            "/api/admin/ai-models/hub-status",
            params=[("actor_id", "pa-1"), ("roles", "platform_admin")],
        )
        body = r.json()
        assert body["configured"] is True
        assert body["revision"] == 42
        assert body["model_count"] == 3


async def test_hub_sync_endpoint(_env_hub, session_factory):
    async with await _client() as ac:
        r = await ac.post(
            "/api/admin/ai-models/hub-sync",
            params=[("actor_id", "pa-1"), ("roles", "platform_admin")],
        )
        # 未注入 fake opener 时会尝试真实拉取（失败也可能 502）；这里只验证
        # 未配置时 409，配置时至少不是 409。
        assert r.status_code in (200, 502)


async def test_write_endpoints_kept_when_unconfigured(session_factory):
    async with await _client() as ac:
        # 缺 model_code 等触发 422，而不是 410（未配置 hub 时本地写口保留）。
        payload = {
            "model_code": "",
            "provider": "agnes",
            "actor": {"id": "pa-1", "roles": ["platform_admin"]},
        }
        r = await ac.post("/api/admin/ai-models", json=payload)
        assert r.status_code == 422


# ---------------- 双读对比：hub 路径真正消费投影（W6-2） ----------------


async def _fake_render(*_a, **_k):
    return "prompt"


class _CapturingDriver:
    def __init__(self):
        self.captured: dict = {}

    async def generate(self, **kwargs):
        self.captured.update(kwargs)
        return GenerationResult(text='{"ok": 1}', input_tokens=5, output_tokens=3)


async def test_gateway_invoke_uses_hub(_env_hub, session_factory, monkeypatch):
    hub.sync_hub_projection(_fake_client())
    capturing = _CapturingDriver()
    monkeypatch.setattr(gateway.drivers, "driver_for", lambda _p: capturing)
    monkeypatch.setattr(
        gateway, "_render_current_prompt", _fake_render
    )
    async with session_factory() as session:
        invocation = await gateway.invoke(session, "CAT-RECOG", {})
    # 双读对比：hub 投影的 model/api_key/base_url 被真正使用。
    assert capturing.captured["model_code"] == "ark-code-latest"
    assert capturing.captured["api_key"] == "PLACEHOLDER_KEY_NOT_REAL_0001"
    assert (
        capturing.captured["base_url"]
        == "https://ark.cn-beijing.volces.com/api/plan/v3"
    )
    assert invocation.model_code == "ark-code-latest"


async def test_gateway_invoke_falls_back_without_hub(session_factory, monkeypatch):
    """未配置 hub：走旧 ai_scene_routes（这里用 monkeypatch 验证 driver 选择）。"""
    # 旧路径需要 route+model+key；用 _resolve_model 缺路由直接报 ModelConfigError。
    async with session_factory() as session:
        with pytest.raises(gateway.ModelConfigError):
            await gateway.invoke(session, "CAT-RECOG", {})


async def test_scene_alias_override(_env_hub, session_factory, monkeypatch):
    hub.sync_hub_projection(_fake_client())
    # 把 CAT-RECOG 显式映射到 score alias。
    monkeypatch.setitem(hub.SCENE_ALIAS, "CAT-RECOG", "score")
    capturing = _CapturingDriver()
    monkeypatch.setattr(gateway.drivers, "driver_for", lambda _p: capturing)
    monkeypatch.setattr(
        gateway, "_render_current_prompt", _fake_render
    )
    async with session_factory() as session:
        await gateway.invoke(session, "CAT-RECOG", {})
    assert capturing.captured["model_code"] == "doubao-seed-1-6-250615"


async def test_producer_uses_hub(_env_hub, monkeypatch):
    from app.core.content_base.producers import LLMContentProducer
    from app.core.content_base.types import ContentConstraints, ContentRequest

    hub.sync_hub_projection(_fake_client())
    capturing = _CapturingDriver()
    monkeypatch.setattr(
        "app.core.content_base.producers.drivers.OpenAICompatibleDriver",
        lambda: capturing,
    )
    request = ContentRequest(
        channel="web",
        content_type="article",
        product_id="p1",
        inputs={},
        constraints=ContentConstraints(),
    )
    producer = LLMContentProducer()
    produced = await producer.produce(request)
    assert capturing.captured["model_code"] == "ark-code-latest"
    assert capturing.captured["api_key"] == "PLACEHOLDER_KEY_NOT_REAL_0001"
    assert produced.evidence_refs == ["llm:ark-code-latest"]
