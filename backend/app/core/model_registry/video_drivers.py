"""段12 真视频生成驱动（Q354）——供应商异步任务，与 chat/embedding 驱动同层但不同形。

契约来源＝官方接入文档 `wiki.agnes-ai.com/zh-Hans/docs/agnes-video-25`（Q353 取证订正）：
- 创建：`POST {base}/videos`，`mode` 必填且只有 `text`／`keyframe`／`reference`，
  `seconds` 为**字符串** "4".."12"，`size` `720P|1080P|1K|2K`，`aspect_ratio` 六值，`n` 固定 1；
  响应同时回 `id`／`task_id`／`video_id`，**轮询用 `video_id`**。
- 轮询：`GET {origin}/agnesapi?video_id=…&model_name=…`（注意是**站点根**，base_url 里的
  `/v1` 要剥掉），`status` 到 `completed` 后取**顶层 `url`**；`failed` 为终态。

三条刻意的纪律：
1. **不重试**。`_post_json`（chat 侧）对 429/5xx 有限重试，这里一次都不重试——花钱动作
   重复提交＝重复计费（Q354 裁决②：`503 video_queue_full`／`failed`／超时一律不自动重投）。
2. **解析严格、失败带回原文**。响应缺 `video_id`／`url` 一律抛 `VideoDriverError` 并把响应体
   前 400 字放进消息，让第一例真实形状不匹配当场可见，而不是被"宽容解析"悄悄吞掉。
3. **未知状态不算终态**。只认 `completed`／`failed`（含 `error` 别名），其余一律"仍在跑"，
   由上层超时口径兜底——不把没见过的中间态猜成成功或失败。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.model_registry.drivers import DriverError, ModelEndpointNotConfigured

_CREATE_PATH = "/videos"
_POLL_PATH = "/agnesapi"
_STATUS_SUCCESS = ("completed", "succeeded")
_STATUS_FAILED = ("failed", "error")
_BODY_SNIPPET = 400


class VideoDriverError(DriverError):
    """供应商视频任务调用失败（形状不符或 HTTP 非 2xx）；上层置终态＋开待办，不重试。"""


@dataclass(frozen=True)
class VideoSubmission:
    video_id: str
    task_id: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class VideoPollResult:
    """`done=True` 只可能是 completed 或 failed；其余状态一律 done=False（仍在跑）。"""

    done: bool
    succeeded: bool
    url: str | None
    vendor_status: str
    error: str | None
    raw: dict[str, Any]


def _base_url(provider: str) -> str:
    base = (os.environ.get(f"LOOM_LLM_BASE_URL_{provider.upper()}") or "").rstrip("/")
    if not base:
        raise ModelEndpointNotConfigured(
            f"video provider base_url missing: set LOOM_LLM_BASE_URL_{provider.upper()}"
        )
    return base


def _origin(base_url: str) -> str:
    """`https://host/v1` → `https://host`：官方轮询端点在站点根上，不带版本段。"""
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _timeout() -> float:
    return float(os.environ.get("LOOM_LLM_HTTP_TIMEOUT_SECONDS", "60"))


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _snippet(resp: httpx.Response) -> str:
    return f"{resp.status_code}: {resp.text[:_BODY_SNIPPET]}"


def _json_dict(body: Any, where: str) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise VideoDriverError(f"{where} returned a non-object body: {str(body)[:_BODY_SNIPPET]}")
    return body


async def submit_video_task(
    *,
    provider: str,
    model_code: str,
    api_key: str,
    prompt: str,
    mode: str,
    seconds: int,
    size: str,
    aspect_ratio: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> VideoSubmission:
    """创建一次供应商视频任务。单次请求，绝不重试（重复提交＝重复花钱）。

    `transport` 只是测试缝（真调用一律 None）：单测因此能跑过**真实 httpx 请求/响应栈**
    来验证本模块的解析与判定，而不是把本函数换成假实现。
    """
    base = _base_url(provider)
    payload = {
        "model": model_code,
        "prompt": prompt,
        "mode": mode,
        "seconds": str(seconds),
        "size": size,
        "aspect_ratio": aspect_ratio,
        "n": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=_timeout(), transport=transport) as client:
            resp = await client.post(f"{base}{_CREATE_PATH}", headers=_headers(api_key), json=payload)
    except httpx.TransportError as exc:
        raise VideoDriverError(f"video submit transport failure: {exc!r}") from exc
    if resp.status_code // 100 != 2:
        raise VideoDriverError(f"video submit rejected: {_snippet(resp)}")
    data = _json_dict(resp.json(), "video submit")
    video_id = data.get("video_id")
    if not isinstance(video_id, str) or not video_id:
        # 官方形状必有 video_id（轮询唯一凭据）；缺它就是形状不符，不能靠猜 id/task_id 顶上。
        raise VideoDriverError(f"video submit response has no usable video_id: {data}")
    task_id = data.get("task_id") or data.get("id")
    return VideoSubmission(
        video_id=video_id,
        task_id=task_id if isinstance(task_id, str) else None,
        raw=data,
    )


async def poll_video_task(
    *,
    provider: str,
    model_code: str,
    api_key: str,
    video_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> VideoPollResult:
    """查一次任务状态。单次请求，不重试（轮询本身不花钱，但失败交给下一轮 tick）。"""
    base = _base_url(provider)
    url = f"{_origin(base)}{_POLL_PATH}"
    try:
        async with httpx.AsyncClient(timeout=_timeout(), transport=transport) as client:
            resp = await client.get(
                url,
                headers=_headers(api_key),
                params={"video_id": video_id, "model_name": model_code},
            )
    except httpx.TransportError as exc:
        raise VideoDriverError(f"video poll transport failure: {exc!r}") from exc
    if resp.status_code // 100 != 2:
        raise VideoDriverError(f"video poll rejected: {_snippet(resp)}")
    data = _json_dict(resp.json(), "video poll")
    status = str(data.get("status") or "")
    lowered = status.lower()
    if lowered in _STATUS_SUCCESS:
        url_value = data.get("url")
        if not isinstance(url_value, str) or not url_value:
            raise VideoDriverError(f"video task completed without a url: {data}")
        return VideoPollResult(
            done=True, succeeded=True, url=url_value, vendor_status=status, error=None, raw=data
        )
    if lowered in _STATUS_FAILED:
        reason = data.get("error") or data.get("message") or status or "vendor reported failure"
        return VideoPollResult(
            done=True,
            succeeded=False,
            url=None,
            vendor_status=status,
            error=str(reason)[:1000],
            raw=data,
        )
    return VideoPollResult(
        done=False, succeeded=False, url=None, vendor_status=status, error=None, raw=data
    )
