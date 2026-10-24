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
from app.core.model_registry import drivers

DEFAULT_PROVIDER = "agnes"
DEFAULT_MODEL_CODE = "agnes-3.0-flash"


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
    """真实模型产出。provider/model 可由环境变量覆盖。"""

    def __init__(
        self,
        *,
        provider: str | None = None,
        model_code: str | None = None,
    ) -> None:
        self._provider = provider or os.environ.get(
            "LOOM_CONTENT_PROVIDER", DEFAULT_PROVIDER
        )
        self._model_code = model_code or os.environ.get(
            "LOOM_CONTENT_MODEL", DEFAULT_MODEL_CODE
        )

    def _api_key(self) -> str:
        key = (
            os.environ.get("LOOM_LLM_KEY_AGNES")
            or os.environ.get("LOOM_E2E_AGNES_KEY")
        )
        if not key:
            raise drivers.ModelEndpointNotConfigured(
                "content LLM key missing: set LOOM_LLM_KEY_AGNES"
            )
        return key

    async def produce(self, request: ContentRequest) -> ProducedContent:
        result = await drivers.driver_for(self._provider).generate(
            scene="CONTENT-BASE",
            user_message=_build_prompt(request),
            variables={},
            model_code=self._model_code,
            api_key=self._api_key(),
            provider=self._provider,
        )
        try:
            parsed = json.loads(result.text)
        except json.JSONDecodeError:
            parsed = {"text": result.text}
        return ProducedContent(
            body=_normalize_body(request, parsed),
            evidence_refs=[f"llm:{self._model_code}"],
        )
