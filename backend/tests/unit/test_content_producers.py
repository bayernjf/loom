"""内容产出器单测（M4/T-M4-03）：不触网，driver 用 fake 注入。"""

import pytest

from app.core.content_base.producers import (
    DeterministicProducer,
    LLMContentProducer,
)
from app.core.content_base.types import (
    ContentConstraints,
    ContentRequest,
)
from app.core.model_registry import drivers


def _request(**overrides) -> ContentRequest:
    base = {
        "product_id": "sku-1",
        "channel": "douyin",
        "content_type": "detail",
        "inputs": {"title": "纯棉T恤"},
    }
    base.update(overrides)
    return ContentRequest(**base)


class _FakeDriver:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return drivers.GenerationResult(
            text=self._text, input_tokens=10, output_tokens=20
        )


async def test_deterministic_producer() -> None:
    out = await DeterministicProducer().produce(_request())
    assert out.body["product_id"] == "sku-1"
    assert out.evidence_refs


async def test_llm_producer_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("LOOM_LLM_KEY_AGNES", raising=False)
    monkeypatch.delenv("LOOM_E2E_AGNES_KEY", raising=False)
    with pytest.raises(drivers.ModelEndpointNotConfigured):
        await LLMContentProducer().produce(_request())


async def test_llm_producer_parses_json(monkeypatch) -> None:
    monkeypatch.setenv("LOOM_LLM_KEY_AGNES", "test-key")
    fake = _FakeDriver('{"title":"T","text":"B"}')
    monkeypatch.setitem(
        drivers._DRIVERS, "agnes", fake  # type: ignore[attr-defined]
    )
    out = await LLMContentProducer().produce(_request())
    assert out.body["title"] == "T"
    assert out.body["text"] == "B"
    assert out.evidence_refs == ["llm:agnes-3.0-flash"]
    assert fake.calls[0]["model_code"] == "agnes-3.0-flash"


async def test_llm_producer_falls_back_on_non_json(monkeypatch) -> None:
    monkeypatch.setenv("LOOM_LLM_KEY_AGNES", "test-key")
    monkeypatch.setitem(
        drivers._DRIVERS,  # type: ignore[attr-defined]
        "agnes",
        _FakeDriver("not a json body"),
    )
    out = await LLMContentProducer().produce(_request())
    assert out.body["text"] == "not a json body"


async def test_llm_producer_passes_banned_into_prompt(monkeypatch) -> None:
    monkeypatch.setenv("LOOM_LLM_KEY_AGNES", "test-key")
    fake = _FakeDriver('{"text":"ok"}')
    monkeypatch.setitem(
        drivers._DRIVERS, "agnes", fake  # type: ignore[attr-defined]
    )
    request = _request(
        constraints=ContentConstraints(banned=["最有效"])
    )
    await LLMContentProducer().produce(request)
    assert "最有效" in fake.calls[0]["user_message"]
