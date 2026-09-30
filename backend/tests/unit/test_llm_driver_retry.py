"""LLM 驱动出站重试（Q240）。

`OpenAICompatibleDriver` 此前零单测：它自己 new `httpx.AsyncClient`，故
`httpx.MockTransport` 注入不进去，而本仓没有 `respx`/`pytest-httpx` 依赖。这里按房规
monkeypatch `drivers.httpx.AsyncClient`（`drivers.httpx` 就是全局模块，monkeypatch 会
自动还原）成一个 scripted fake，不加新依赖。

退避常量被置 0，使 `asyncio.sleep` 瞬时返回；测试因此不测退避时长，只测**调用次数**与
**是否重试**这两件真正决定行为的事。
"""

import asyncio
import json

import httpx
import pytest

from app.core.model_registry import drivers

BASE_URL = "https://llm.example.invalid/v1"


class _FakeResp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def _chat_ok(content: str = '{"body": "ok"}') -> _FakeResp:
    return _FakeResp(
        200,
        {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        },
    )


def _embed_ok() -> _FakeResp:
    return _FakeResp(
        200,
        {"data": [{"index": 0, "embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 1}},
    )


class _Script:
    """脚本化的响应序列 + 调用记录。"""

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls: list[dict] = []

    def next_step(self):
        if not self.steps:
            raise AssertionError(
                "fake client 的脚本用完了——被测代码发的请求比测试脚本预期的多。"
                "（若你正在测重试，这就是重试次数超预期。）"
            )
        return self.steps.pop(0)


class _FakeClient:
    def __init__(self, script: _Script, **_):
        self._script = script

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, *, headers=None, json=None):
        self._script.calls.append({"url": url, "headers": headers, "json": json})
        step = self._script.next_step()
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def scripted(monkeypatch):
    """安装 scripted fake client；返回 installer，传给它响应序列。

    环境变量走 installer 的参数而不是测试体里的 `monkeypatch.setenv`——否则 fixture
    的清理会盖掉测试刚设的值（顺序一错就变成静默用默认值）。
    """

    def _install(steps, *, max_attempts=None, base_url=BASE_URL, backoff_base=0.0) -> _Script:
        script = _Script(steps)
        monkeypatch.setattr(drivers.httpx, "AsyncClient", lambda **kw: _FakeClient(script, **kw))
        monkeypatch.setattr(drivers, "RETRY_BACKOFF_BASE_SECONDS", backoff_base)
        if base_url is None:
            monkeypatch.delenv("LOOM_LLM_BASE_URL_AGNES", raising=False)
        else:
            monkeypatch.setenv("LOOM_LLM_BASE_URL_AGNES", base_url)
        if max_attempts is None:
            monkeypatch.delenv("LOOM_LLM_MAX_ATTEMPTS", raising=False)
        else:
            monkeypatch.setenv("LOOM_LLM_MAX_ATTEMPTS", str(max_attempts))
        return script

    return _install


async def _generate():
    return await drivers.OpenAICompatibleDriver().generate(
        scene="ARTICLE-GEN",
        model_code="agnes-2.5-flash",
        user_message="hi",
        api_key="k",
        provider="agnes",
    )


async def _embed():
    return await drivers.OpenAICompatibleDriver().embed(
        scene="ATOM-AFFINITY",
        model_code="agnes-embed",
        texts=["a"],
        api_key="k",
        provider="agnes",
    )


# --- 会重试的失败 ---------------------------------------------------------


async def test_retries_transport_error_then_succeeds(scripted):
    script = scripted([httpx.RemoteProtocolError("Server disconnected"), _chat_ok()])

    result = await _generate()

    assert result.text == '{"body": "ok"}'
    assert len(script.calls) == 2
    assert script.calls[0]["url"] == f"{BASE_URL}/chat/completions"
    assert script.calls[0]["headers"] == {"Authorization": "Bearer k"}


async def test_retries_429_then_succeeds(scripted):
    script = scripted([_FakeResp(429, {"error": "slow down"}), _chat_ok()])

    result = await _generate()

    assert result.text == '{"body": "ok"}'
    assert len(script.calls) == 2


async def test_retries_5xx_then_succeeds(scripted):
    script = scripted([_FakeResp(503, {"error": "upstream"}), _chat_ok()])

    result = await _generate()

    assert result.text == '{"body": "ok"}'
    assert len(script.calls) == 2


# --- 不会重试的失败 -------------------------------------------------------


@pytest.mark.parametrize("status", [400, 403, 404, 422])
async def test_does_not_retry_other_4xx(scripted, status):
    """除 429 外的 4xx 是确定性拒绝，重试只烧钱烧延迟。"""
    script = scripted([_FakeResp(status, {"error": "nope"})])

    with pytest.raises(drivers.DriverError, match=f"returned {status}"):
        await _generate()

    assert len(script.calls) == 1


# --- 次数耗尽 -------------------------------------------------------------


async def test_exhausts_attempts_and_raises_driver_error(scripted):
    script = scripted([httpx.ConnectError("boom")] * drivers.DEFAULT_MAX_ATTEMPTS)

    with pytest.raises(drivers.DriverError, match="after 3 attempts"):
        await _generate()

    assert len(script.calls) == drivers.DEFAULT_MAX_ATTEMPTS


async def test_max_attempts_knob_is_honored(scripted):
    script = scripted([httpx.ConnectError("boom")] * 5, max_attempts=5)

    with pytest.raises(drivers.DriverError, match="after 5 attempts"):
        await _generate()

    assert len(script.calls) == 5


async def test_max_attempts_zero_means_no_retry(scripted):
    """`0` 退化成"不重试"（1 次调用），而不是"不调用"。"""
    script = scripted([httpx.ConnectError("boom")], max_attempts=0)

    with pytest.raises(drivers.DriverError, match="after 1 attempts"):
        await _generate()

    assert len(script.calls) == 1


# --- 两个调用方共用同一条重试路径 ----------------------------------------


async def test_embed_shares_the_same_retry_path(scripted):
    script = scripted([httpx.ReadTimeout("slow"), _embed_ok()])

    result = await _embed()

    assert result.vectors == [[0.1, 0.2]]
    assert len(script.calls) == 2
    assert script.calls[0]["url"] == f"{BASE_URL}/embeddings"


# --- 退避 -----------------------------------------------------------------


def test_retry_delay_is_exponential_and_capped():
    assert [drivers._retry_delay(a) for a in range(1, 5)] == [0.5, 1.0, 2.0, 4.0]
    assert drivers._retry_delay(20) == drivers.RETRY_BACKOFF_CAP_SECONDS


class _AsyncioShim:
    """只拦 `sleep`，其余透传给真 asyncio。

    刻意不 patch 全局 `asyncio.sleep`——那会波及事件循环自身的调度。
    """

    def __init__(self, slept: list):
        self._slept = slept

    async def sleep(self, seconds):
        self._slept.append(seconds)

    def __getattr__(self, name):
        return getattr(asyncio, name)


async def test_backoff_sleeps_between_attempts_but_not_after_the_last(scripted, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(drivers, "asyncio", _AsyncioShim(slept))
    scripted([httpx.ConnectError("boom")] * 3, backoff_base=0.5)

    with pytest.raises(drivers.DriverError):
        await _generate()

    # 3 次尝试之间睡 2 次；最后一次失败后不再睡。
    assert slept == [0.5, 1.0]


# --- 正向对照 -------------------------------------------------------------


async def test_the_fake_client_can_actually_fail_and_succeed(scripted):
    """正向对照：证明这个 fake 真的能成功、也真的能失败——否则上面全是空断言。"""
    ok = scripted([_chat_ok('{"body": "x"}')])
    assert (await _generate()).text == '{"body": "x"}'
    assert len(ok.calls) == 1

    bad = scripted([httpx.ConnectError("boom")] * drivers.DEFAULT_MAX_ATTEMPTS)
    with pytest.raises(drivers.DriverError):
        await _generate()
    assert len(bad.calls) == drivers.DEFAULT_MAX_ATTEMPTS


async def test_missing_base_url_does_not_reach_the_http_layer(scripted):
    """base_url 解析留在调用方：`ModelEndpointNotConfigured` 不被重试 helper 吞掉。"""
    script = scripted([], base_url=None)

    with pytest.raises(drivers.ModelEndpointNotConfigured):
        await _generate()

    assert script.calls == []
