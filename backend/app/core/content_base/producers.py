"""内容产出器（M4/T-M4-03）：把 ContentRequest 转为候选 body。

- DeterministicProducer：确定性组装，测试/离线用（不触网）。
- LLMContentProducer：经 OpenAI 兼容驱动调真实模型（默认 agnes-3.0-flash），
  key 从环境变量读，不进 DB、不入库。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.content_base import assembly
from app.core.content_base.types import ContentRequest
from app.core.model_registry import drivers, hub

DEFAULT_PROVIDER = "agnes"
DEFAULT_MODEL_CODE = "agnes-3.0-flash"
CONTENT_SCENE = "CONTENT-BASE"


@dataclass(frozen=True)
class ProducedContent:
    body: dict[str, Any]
    evidence_refs: list[str]


class ContentProducer(Protocol):
    async def produce(self, request: ContentRequest) -> ProducedContent: ...


class DeterministicProducer:
    async def produce(self, request: ContentRequest) -> ProducedContent:
        return ProducedContent(
            body=assembly.assemble_body(request),
            evidence_refs=["content-base:deterministic-assembly"],
        )


def _build_prompt(request: ContentRequest) -> str:
    c = request.constraints
    intro = f"你是电商内容创作助手，为发布渠道 {request.channel} 生成 content_type={request.content_type} 的电商内容。"
    lines = [intro, f"产品信息（JSON）：{json.dumps(request.inputs, ensure_ascii=False)}"]
    if c.brand:
        lines.append(f"品牌词（保持口径）：{', '.join(c.brand)}")
    if c.wordlist:
        lines.append(f"可用/合规词：{', '.join(c.wordlist)}")
    if c.banned:
        lines.append(f"禁用词（严禁出现）：{', '.join(c.banned)}")
    lines.append(
        "只输出一个 JSON 对象：基础字段为 \"title\"（标题）与 \"text\"（正文）；"
        "short_video_script 可加 \"scenes\"（分镜数组，每项含 shot/voice）；"
        "qa 类型可加 \"qa_pairs\"（question/answer 数组）。"
        "内容必须真实、不夸大、不做绝对化承诺、不出现禁用词。"
    )
    return "\n".join(lines)


def _normalize_body(request: ContentRequest, parsed: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "content_type": request.content_type,
        "channel": request.channel,
        "product_id": request.product_id,
    }
    if isinstance(parsed, dict):
        body.update(parsed)
    else:
        body["text"] = str(parsed)
    return body


class LLMContentProducer:
    """真实模型产出。

    hub 配置时：model/api_key/base_url 从 hub 投影解析（CONTENT-BASE 场景，
    scene 即 alias）；否则回退环境变量（LOOM_CONTENT_PROVIDER/MODEL/
    LOOM_LLM_KEY_AGNES），迁移期保留。
    """

    def __init__(
        self,
        *,
        provider: str | None = None,
        model_code: str | None = None,
    ) -> None:
        self._provider_override = provider
        self._model_override = model_code

    def _env_fallback(self) -> tuple[str, str, str | None, str | None]:
        """回退路径：provider/model/api_key/base_url 从 env。"""
        provider = self._provider_override or os.environ.get(
            "LOOM_CONTENT_PROVIDER", DEFAULT_PROVIDER
        )
        model_code = self._model_override or os.environ.get(
            "LOOM_CONTENT_MODEL", DEFAULT_MODEL_CODE
        )
        key = (
            os.environ.get("LOOM_LLM_KEY_AGNES")
            or os.environ.get("LOOM_E2E_AGNES_KEY")
        )
        if not key:
            raise drivers.ModelEndpointNotConfigured(
                "content LLM key missing: set LOOM_LLM_KEY_AGNES"
            )
        return provider, model_code, key, None

    async def produce(self, request: ContentRequest) -> ProducedContent:
        # 优先 hub 投影。
        provider = model_code = api_key = base_url = None
        if hub.is_hub_configured():
            resolved = hub.resolve_for_scene(CONTENT_SCENE, "text")
            if resolved is not None:
                provider = resolved.provider
                model_code = resolved.model
                api_key = resolved.api_key
                base_url = resolved.base_url
        if provider is None or model_code is None or api_key is None:
            provider, model_code, api_key, base_url = self._env_fallback()

        kwargs: dict[str, Any] = {
            "model_code": model_code,
            "api_key": api_key,
            "provider": provider,
        }
        if base_url is not None:
            kwargs["base_url"] = base_url
        result = await drivers.driver_for(provider).generate(
            scene=CONTENT_SCENE,
            user_message=_build_prompt(request),
            variables={},
            **kwargs,
        )
        try:
            parsed = json.loads(result.text)
        except json.JSONDecodeError:
            parsed = {"text": result.text}
        return ProducedContent(
            body=_normalize_body(request, parsed),
            evidence_refs=[f"llm:{model_code}"],
        )
