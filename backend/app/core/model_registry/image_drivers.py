"""文生图驱动（W6-3）——同步图像生成，模型/凭证/base_url 来自 hub 投影。

与 video_drivers 同层但不同形：图像生成是**同步**请求（POST 到 images 端点，
响应直接回图片 URL/b64），不像视频需要异步轮询。

三条纪律（与视频一致）：
1. **不重试**。花钱动作重复提交＝重复计费；429/5xx/传输错一律抛出，由人决定。
2. **解析严格、失败带回原文**。响应缺 ``data[].url`` 一律抛 ImageDriverError
   并把响应体前 400 字放进消息，让第一例真实形状不匹配当场可见。
3. **base_url 优先 hub 投影注入**，否则回退 env（迁移期）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.model_registry.drivers import DriverError

_DEFAULT_IMAGES_PATH = "/images/generations"
_BODY_SNIPPET = 400


class ImageDriverError(DriverError):
    """图像生成调用失败（形状不符或 HTTP 非 2xx）；上层不重试。"""


@dataclass(frozen=True)
class ImageResult:
    images: list[str]  # 图片 URL（或 b64 数据，由调用方按返回字段处理）
    raw: dict[str, Any]


def _base_url(provider: str, base_url: str | None = None) -> str:
    base = (
        base_url
        or os.environ.get(f"LOOM_LLM_BASE_URL_{provider.upper()}")
        or ""
    ).rstrip("/")
    if not base:
        raise DriverError(
            f"image provider base_url missing: set LOOM_LLM_BASE_URL_{provider.upper()}"
        )
    return base


def _timeout() -> float:
    return float(os.environ.get("LOOM_LLM_HTTP_TIMEOUT_SECONDS", "60"))


def _extract_images(data: dict[str, Any]) -> list[str]:
    items = data.get("data")
    if not isinstance(items, list) or not items:
        raise ImageDriverError(
            f"image response has no data[]: {str(data)[:_BODY_SNIPPET]}"
        )
    images: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            raise ImageDriverError(
                f"image data item is not an object: {str(item)[:_BODY_SNIPPET]}"
            )
        value = item.get("url") or item.get("b64_json")
        if not isinstance(value, str) or not value:
            raise ImageDriverError(
                f"image data item has no url/b64_json: {str(item)[:_BODY_SNIPPET]}"
            )
        images.append(value)
    return images


async def generate_image(
    *,
    provider: str,
    model_code: str,
    api_key: str,
    prompt: str,
    base_url: str | None = None,
    images_path: str | None = None,
    size: str | None = None,
    n: int = 1,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ImageResult:
    """生成一次图片。单次请求，绝不重试（重复提交＝重复花钱）。

    `images_path` 由 hub 投影 ``endpoints.images`` 给出，默认
    /images/generations；`transport` 只是测试缝（真调用一律 None）。
    """
    base = _base_url(provider, base_url)
    path = images_path or _DEFAULT_IMAGES_PATH
    payload: dict[str, Any] = {"model": model_code, "prompt": prompt, "n": n}
    if size is not None:
        payload["size"] = size
    try:
        async with httpx.AsyncClient(timeout=_timeout(), transport=transport) as client:
            resp = await client.post(
                f"{base}{path}",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
    except httpx.TransportError as exc:
        raise ImageDriverError(f"image transport failure: {exc!r}") from exc
    if resp.status_code // 100 != 2:
        raise ImageDriverError(
            f"image request rejected: {resp.status_code}: {resp.text[:_BODY_SNIPPET]}"
        )
    data = resp.json()
    if not isinstance(data, dict):
        raise ImageDriverError(f"image response is not an object: {str(data)[:_BODY_SNIPPET]}")
    return ImageResult(images=_extract_images(data), raw=data)
