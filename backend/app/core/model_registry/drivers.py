"""LLM 驱动层（Q82-2）：合成确定性替身（本地/测试默认）与 OpenAI 兼容远程驱动。

驱动选择按 ai_models.provider：synthetic → 确定性替身；其余按 OpenAI Chat
Completions 兼容协议调用，base_url 只从环境变量 LOOM_LLM_BASE_URL_<PROVIDER>
注入（环境变量只承载端点/密钥，不承载业务配置，docs/15 §4）。
"""

import asyncio
import json
import os
from dataclasses import dataclass

import httpx

from app.core.model_registry import synthetic


@dataclass(frozen=True)
class GenerationResult:
    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    input_tokens: int


def _token_count(text: str) -> int:
    # 确定性近似计数（替身与预算估算用；真实计费以供应商 usage 为准）。
    return max(1, len(text) // 4)


def _http_timeout() -> float:
    return float(os.environ.get("LOOM_LLM_HTTP_TIMEOUT_SECONDS", "60"))


class DriverError(Exception):
    pass


class ModelEndpointNotConfigured(DriverError):
    pass


# Q240 出站重试：传输层异常与 429/5xx 重试，其余 4xx 立即失败。
# 次数是 operator 旋钮（os.environ 直读，同 _http_timeout）；退避参数是常量，
# 形制照 config_center/broadcast.py 的 Q140 指数退避，封顶兜住 MAX_ATTEMPTS 设很大。
DEFAULT_MAX_ATTEMPTS = 3
RETRY_BACKOFF_BASE_SECONDS = 0.5
RETRY_BACKOFF_CAP_SECONDS = 30.0


def _max_attempts() -> int:
    # 0/1 都表示"不重试"：写错 0 退化成不重试，而不是不调用。
    return max(1, int(os.environ.get("LOOM_LLM_MAX_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS))))


def _retry_delay(attempt: int) -> float:
    return min(RETRY_BACKOFF_CAP_SECONDS, RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))


async def _post_json(*, url: str, api_key: str, payload: dict) -> dict:
    """带有限重试的 JSON POST，返回已解析的响应体。

    重试 `httpx.TransportError`（覆盖 RemoteProtocolError/连接错误/全部超时类）与
    429/5xx；其余 4xx 是确定性拒绝，重试只烧钱烧延迟。次数耗尽抛 DriverError 并
    链上最后一次原因，供 gateway 映射为 GenerationUpstreamError。
    """
    attempts = _max_attempts()
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=_http_timeout()) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
        except httpx.TransportError as exc:
            last = exc
        else:
            if resp.status_code // 100 == 2:
                return resp.json()
            detail = f"LLM provider returned {resp.status_code}: {resp.text[:200]}"
            if resp.status_code != 429 and resp.status_code < 500:
                raise DriverError(detail)
            last = DriverError(detail)
        if attempt < attempts:
            await asyncio.sleep(_retry_delay(attempt))
    raise DriverError(f"LLM call failed after {attempts} attempts: {last}") from last


class SyntheticDriver:
    """无凭证环境的确定性替身：按 scene 注册的构造器产出结构化 JSON/向量。"""

    async def generate(self, *, scene: str, user_message: str, variables: dict, **_) -> GenerationResult:
        builder = synthetic.BUILDERS.get(scene)
        if builder is None:
            raise DriverError(f"synthetic driver has no builder for scene {scene!r}")
        text = json.dumps(builder(variables), ensure_ascii=False)
        return GenerationResult(
            text=text,
            input_tokens=_token_count(user_message),
            output_tokens=_token_count(text),
        )

    async def embed(self, *, scene: str, texts: list[str], **_) -> EmbeddingResult:
        builder = synthetic.EMBED_BUILDERS.get(scene)
        if builder is None:
            raise DriverError(f"synthetic driver has no embed builder for scene {scene!r}")
        vectors = builder(texts)
        return EmbeddingResult(
            vectors=vectors,
            input_tokens=sum(_token_count(t) for t in texts),
        )


class OpenAICompatibleDriver:
    """OpenAI Chat Completions 兼容驱动（Bearer Key + JSON 模式）。"""

    async def generate(
        self,
        *,
        scene: str,
        model_code: str,
        user_message: str,
        api_key: str,
        provider: str,
        **_,
    ) -> GenerationResult:
        base_url = os.environ.get(f"LOOM_LLM_BASE_URL_{provider.upper()}")
        if not base_url:
            raise ModelEndpointNotConfigured(
                f"remote LLM base_url missing: set LOOM_LLM_BASE_URL_{provider.upper()}"
            )
        data = await _post_json(
            url=f"{base_url.rstrip('/')}/chat/completions",
            api_key=api_key,
            payload={
                "model": model_code,
                "messages": [{"role": "user", "content": user_message}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return GenerationResult(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", _token_count(user_message))),
            output_tokens=int(usage.get("completion_tokens", _token_count(text))),
        )

    async def embed(
        self,
        *,
        scene: str,
        model_code: str,
        texts: list[str],
        api_key: str,
        provider: str,
        **_,
    ) -> EmbeddingResult:
        base_url = os.environ.get(f"LOOM_LLM_BASE_URL_{provider.upper()}")
        if not base_url:
            raise ModelEndpointNotConfigured(
                f"remote LLM base_url missing: set LOOM_LLM_BASE_URL_{provider.upper()}"
            )
        data = await _post_json(
            url=f"{base_url.rstrip('/')}/embeddings",
            api_key=api_key,
            payload={"model": model_code, "input": texts},
        )
        rows = sorted(data["data"], key=lambda row: row["index"])
        if len(rows) != len(texts):
            raise DriverError("embedding response row count does not match input count")
        usage = data.get("usage", {})
        return EmbeddingResult(
            vectors=[list(map(float, row["embedding"])) for row in rows],
            input_tokens=int(usage.get("prompt_tokens", sum(_token_count(t) for t in texts))),
        )


_DRIVERS: dict = {
    "synthetic": SyntheticDriver(),
    "openai": OpenAICompatibleDriver(),
}


def driver_for(provider: str):
    driver = _DRIVERS.get(provider)
    if driver is None:
        # 未登记的供应商不静默落到替身（避免把真调用当假数据）。
        raise DriverError(f"no LLM driver registered for provider {provider!r}")
    return driver
