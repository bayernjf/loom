"""Q354 真视频驱动单测：在**真实 httpx 请求/响应栈**上验证解析与"绝不重试"。

测试缝是 `transport=httpx.MockTransport(...)`——被替换的是网络，不是本模块的代码：
所以这里跑的是真的 URL 拼装、header、状态码分支与 JSON 解析。供应商侧真实成功形状
尚未观测到（Q353/Q354 现测 10 发全 `503 video_queue_full`），故本文件的响应体是
**照官方接入文档逐字段构造**的，并在文件末把"真供应商"那条路留成 env 门控的 skip 用例，
而不是把替身跑绿当成真链路已验。
"""

import json
import os

import httpx
import pytest

from app.core.model_registry import video_drivers
from app.core.model_registry.drivers import ModelEndpointNotConfigured

PROVIDER = "agnes"
BASE = "https://apihub.agnes-ai.test/v1"


@pytest.fixture(autouse=True)
def _base_url(monkeypatch):
    monkeypatch.setenv(f"LOOM_LLM_BASE_URL_{PROVIDER.upper()}", BASE)
    monkeypatch.delenv("LOOM_LLM_MAX_ATTEMPTS", raising=False)


def _handler(responses: list[tuple[int, object]], calls: list[httpx.Request]):
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        status, body = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(body, (str, bytes)):
            return httpx.Response(status, text=str(body))
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


async def _submit(responses, calls):
    return await video_drivers.submit_video_task(
        provider=PROVIDER,
        model_code="agnes-video-2.5-flash",
        api_key="sk-test",
        prompt="a red cube turning",
        mode="text",
        seconds=4,
        size="720P",
        aspect_ratio="16:9",
        transport=_handler(responses, calls),
    )


async def _poll(responses, calls):
    return await video_drivers.poll_video_task(
        provider=PROVIDER,
        model_code="agnes-video-2.5-flash",
        api_key="sk-test",
        video_id="vid-1",
        transport=_handler(responses, calls),
    )


async def test_submit_sends_the_documented_shape_and_returns_video_id():
    calls: list[httpx.Request] = []
    submission = await _submit(
        [(200, {"id": "task-9", "task_id": "task-9", "video_id": "vid-1"})], calls
    )
    assert submission.video_id == "vid-1"
    assert submission.task_id == "task-9"
    assert len(calls) == 1
    request = calls[0]
    assert str(request.url) == f"{BASE}/videos"
    assert request.headers["Authorization"] == "Bearer sk-test"
    payload = json.loads(request.content)
    # 官方文档：seconds 是字符串、n 固定 1、mode 必填。
    assert payload["seconds"] == "4"
    assert payload["n"] == 1
    assert payload["mode"] == "text"
    assert payload["model"] == "agnes-video-2.5-flash"


async def test_submit_never_retries_even_on_5xx():
    """花钱动作重投＝重复计费，所以本驱动一次都不重试（Q354 裁决②）。"""
    calls: list[httpx.Request] = []
    with pytest.raises(video_drivers.VideoDriverError):
        await _submit([(500, {"code": "internal"})], calls)
    assert len(calls) == 1, "视频提交被重试了＝可能重复扣费"


async def test_submit_reports_queue_full_body_verbatim():
    """现网实测到的唯一真实响应（`503 video_queue_full`）必须原样进错误消息。"""
    calls: list[httpx.Request] = []
    with pytest.raises(video_drivers.VideoDriverError) as exc:
        await _submit(
            [(503, '{"code":"video_queue_full","message":"video queue is full, please retry later"}')],
            calls,
        )
    assert "video_queue_full" in str(exc.value)
    assert len(calls) == 1


async def test_submit_requires_video_id_and_does_not_guess_from_task_id():
    """只有 `id`/`task_id` 不够——轮询凭据是 `video_id`，缺它就是形状不符。"""
    calls: list[httpx.Request] = []
    with pytest.raises(video_drivers.VideoDriverError, match="no usable video_id"):
        await _submit([(200, {"id": "task-9", "task_id": "task-9"})], calls)


async def test_submit_rejects_non_object_body():
    calls: list[httpx.Request] = []
    with pytest.raises(video_drivers.VideoDriverError, match="non-object body"):
        await _submit([(200, '["not","an","object"]')], calls)


async def test_poll_hits_site_root_and_carries_model_name():
    """轮询端点在**站点根**（base_url 的 `/v1` 必须剥掉），且带 `model_name`。"""
    calls: list[httpx.Request] = []
    result = await _poll(
        [(200, {"status": "completed", "url": "https://cdn.test/v.mp4"})], calls
    )
    assert str(calls[0].url) == (
        "https://apihub.agnes-ai.test/agnesapi?video_id=vid-1&model_name=agnes-video-2.5-flash"
    )
    assert result.done and result.succeeded and result.url == "https://cdn.test/v.mp4"


@pytest.mark.parametrize("status", ["processing", "queued", "in_progress", ""])
async def test_unknown_or_running_status_is_not_terminal(status):
    """没见过的状态既不算成功也不算失败——由超时口径收口（禁把未知猜成终态）。"""
    calls: list[httpx.Request] = []
    result = await _poll([(200, {"status": status})], calls)
    assert result.done is False
    assert result.url is None


async def test_completed_without_url_is_a_shape_error():
    calls: list[httpx.Request] = []
    with pytest.raises(video_drivers.VideoDriverError, match="without a url"):
        await _poll([(200, {"status": "completed"})], calls)


async def test_failed_status_carries_the_vendor_reason():
    calls: list[httpx.Request] = []
    result = await _poll([(200, {"status": "failed", "error": "nsfw detected"})], calls)
    assert result.done and not result.succeeded
    assert "nsfw detected" in (result.error or "")


def test_missing_base_url_fails_loudly(monkeypatch):
    monkeypatch.delenv(f"LOOM_LLM_BASE_URL_{PROVIDER.upper()}", raising=False)
    with pytest.raises(ModelEndpointNotConfigured):
        video_drivers._base_url(PROVIDER)


async def test_real_vendor_success_path_is_not_assumed():
    """真供应商成功路径**未验证**（Q353/Q354 现测 10 发全 `503 video_queue_full`）。

    给了凭证才真跑一次；否则明确 skip——把"替身跑绿"当成"链路已通"是本仓反复登记过的那类错。
    """
    key = os.environ.get("LOOM_E2E_AGNES_KEY")
    base = os.environ.get("LOOM_LLM_BASE_URL_AGNES")
    if not key or not base:
        pytest.skip("real agnes video run needs LOOM_E2E_AGNES_KEY + LOOM_LLM_BASE_URL_AGNES")
    submission = await video_drivers.submit_video_task(
        provider="agnes",
        model_code="agnes-video-2.5-flash",
        api_key=key,
        prompt="a red cube slowly turning on a white table",
        mode="text",
        seconds=4,
        size="720P",
        aspect_ratio="16:9",
    )
    assert submission.video_id
