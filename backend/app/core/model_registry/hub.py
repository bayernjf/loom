"""model-hub 投影同步与解析（W6-1）。

loom 内置模型不再由本地注册表/Key 表维护：本模块用 ``model_hub_client`` 拉取
hub 投影（多条模型），把 **api_key 用 loom 自己的信封（model_registry/crypto.py，
Fernet）加密后**保存在进程内，运行时解析为明文 model/api_key/base_url。

持久化（不新增 migration，不改 ai_models 表结构）：
- 投影为进程级单例；client 的 0600 缓存文件作离线兜底（重启后可先读缓存）。
- 不再从 ai_model_keys 读写内置 key（key 只存 hub）。

解析优先级（内置层换源，与 gateway 收口配合）：
    显式节点 model > （无 BYOK 面）> **hub 投影** > synthetic 替身。

凭证纪律：hub 投影含明文 api_key，但只在拉取点内存里用于加密，随后即弃；
进程内单例/缓存文件中只有信封或 client 缓存（client 缓存为 hub 下发的投影，
仅作离线兜底，访问权限 0600）。
"""

from __future__ import annotations

import logging
import os
import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

#: loom 在 hub 中的 project slug。
HUB_PROJECT_SLUG = "loom"

DEFAULT_CACHE_PATH = "./data/model-hub-cache.json"
DEFAULT_MODALITY = "text"


@dataclass
class HubModelRecord:
    """投影中的一条模型；api_key 为 loom 信封，进程内零明文落盘。"""

    assignment_id: str
    alias: str | None
    role: str
    model: str  # 发给厂商的模型 id
    raw_model: str  # hub 原始 model 名
    api_key_enc: str
    base_url: str
    modalities: list[str]
    endpoints: dict[str, Any]
    adapter: dict[str, Any] | None
    pricing: dict[str, Any] | None
    is_default: bool
    provider: str = ""
    daily_budget_micros: int | None = None


@dataclass
class HubProjection:
    """一次 hub 投影（多条模型 + 修订号）。"""

    revision: int
    models: list[HubModelRecord]


@dataclass
class ResolvedHubModel:
    """解析后的明文模型（只活在调用点内存）。"""

    model: str
    api_key: str
    base_url: str
    assignment_id: str
    alias: str | None
    provider: str
    endpoints: dict[str, Any]
    modalities: list[str]
    # 文本单价（per 1M）与日预算（None=不限），供 gateway 计费/预算硬停。
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0
    daily_budget: float | None = None
    currency_code: str | None = None


# ---------------- 配置 ----------------


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def hub_settings() -> tuple[str, str, str] | None:
    """返回 (hub_url, token, cache_path)；未配置时 None。

    W7-3：MODEL_HUB_DISABLED kill switch 已随旧 env 一并下线——hub 是唯一
    模型源，没有 env 退路可静默跳过。
    """
    hub_url = _env("MODEL_HUB_URL")
    token = _env("MODEL_HUB_TOKEN")
    if not hub_url or not token:
        return None
    cache_path = _env("MODEL_HUB_CACHE_PATH") or DEFAULT_CACHE_PATH
    return hub_url.rstrip("/"), token, cache_path


def is_hub_configured() -> bool:
    return hub_settings() is not None


def get_hub_client(opener: Any = None) -> Any:
    """按 env 装配 ModelHubClient；未配置返回 None。"""
    settings = hub_settings()
    if settings is None:
        return None
    from model_hub_client import ModelHubClient

    hub_url, token, cache_path = settings
    return ModelHubClient(hub_url, token, cache_path, opener=opener)


# ---------------- 进程内单例 ----------------

_projection: HubProjection | None = None
_lock = threading.Lock()


def save_projection(projection: HubProjection) -> None:
    """保存投影到进程内单例。"""
    global _projection
    with _lock:
        _projection = deepcopy(projection)


def load_projection() -> HubProjection | None:
    """读取进程内投影单例。"""
    with _lock:
        if _projection is not None:
            return deepcopy(_projection)
    return None


def reset_hub_projection() -> None:
    """测试辅助：清空进程内投影。"""
    global _projection
    with _lock:
        _projection = None


# ---------------- 后台周期刷新 ----------------

REFRESH_INTERVAL_SECONDS = 300.0
_refresh_thread: threading.Thread | None = None
_refresh_stop = threading.Event()
_refresh_thread_lock = threading.Lock()


def _refresh_loop() -> None:
    while not _refresh_stop.wait(REFRESH_INTERVAL_SECONDS):
        try:
            if is_hub_configured():
                sync_hub_projection()
        except Exception as exc:  # noqa: BLE001
            logger.warning("hub projection background refresh failed: %s", exc)


def start_hub_refresh() -> None:
    """启动后台投影刷新线程（5min 一轮；幂等）。"""
    global _refresh_thread
    if not is_hub_configured():
        return
    with _refresh_thread_lock:
        if _refresh_thread is not None and _refresh_thread.is_alive():
            return
        _refresh_stop.clear()
        _refresh_thread = threading.Thread(
            target=_refresh_loop, name="loom-hub-refresh", daemon=True
        )
        _refresh_thread.start()


def stop_hub_refresh(timeout: float = 2.0) -> None:
    """停止后台刷新线程。"""
    global _refresh_thread
    with _refresh_thread_lock:
        if _refresh_thread is None:
            return
        _refresh_stop.set()
        _refresh_thread.join(timeout=timeout)
        _refresh_thread = None


# ---------------- provider 推断 ----------------


_KNOWN_PROVIDERS = {
    "api.openai.com": "openai",
    "api.anthropic.com": "anthropic",
    "api.deepseek.com": "deepseek",
    "dashscope.aliyuncs.com": "qwen",
    "open.bigmodel.cn": "zhipu",
    "api.moonshot.cn": "moonshot",
    "apihub.agnes-ai.com": "agnes",
    "ark.cn-beijing.volces.com": "ark",
}


def provider_from_base_url(base_url: str) -> str:
    """从 base_url 推断 provider 名（与 job-agent/atlas providerFromBaseUrl 同口径）。"""
    from urllib.parse import urlparse

    try:
        host = urlparse(base_url).hostname or base_url
    except ValueError:
        host = base_url
    host = host.lower()
    if host in _KNOWN_PROVIDERS:
        return _KNOWN_PROVIDERS[host]
    bare = host.replace("www.", "")
    parts = bare.split(".")
    if len(parts) >= 2:
        return parts[-2]
    return bare.split(":")[0]


# ---------------- 同步 ----------------


def sync_hub_projection(client: Any = None) -> dict[str, int] | None:
    """拉取 hub 投影 → 加密 api_key → 存进程内。返回 {revision, pulled}；未配置 None。"""
    hub_client = client or get_hub_client()
    if hub_client is None:
        return None
    from app.core.model_registry import crypto

    hub_client.pull()
    models = hub_client.list()

    default_assigned = False
    records: list[HubModelRecord] = []
    for m in models:
        raw_key = str(m.get("api_key", ""))
        api_key_enc = ""
        if raw_key:
            # 复用 loom Fernet 信封；crypto.encrypt 返回 bytes，转字符串存 dataclass。
            api_key_enc = crypto.encrypt(raw_key).decode("ascii")
        is_primary = m.get("role") == "primary"
        is_default = is_primary and not default_assigned
        if is_default:
            default_assigned = True
        base_url = str(m.get("base_url", ""))
        records.append(
            HubModelRecord(
                assignment_id=str(m.get("assignment_id", "")),
                alias=m.get("alias"),
                role=str(m.get("role", "primary")),
                model=str(m.get("model", "")),
                raw_model=str(m.get("model", "")),
                api_key_enc=api_key_enc,
                base_url=base_url,
                modalities=list(m.get("modalities", [])),
                endpoints=dict(m.get("endpoints", {})),
                adapter=(
                    dict(m["adapter"]) if m.get("adapter") is not None else None
                ),
                pricing=(
                    dict(m["pricing"]) if m.get("pricing") is not None else None
                ),
                is_default=is_default,
                provider=provider_from_base_url(base_url),
                daily_budget_micros=(
                    int(m["daily_budget_micros"])
                    if m.get("daily_budget_micros") is not None
                    else None
                ),
            )
        )

    revision = hub_client.revision or 0
    projection = HubProjection(revision=int(revision), models=records)
    save_projection(projection)
    return {"revision": int(revision), "pulled": len(records)}


# ---------------- 解析 ----------------


def resolve_hub_model(
    modality: str = DEFAULT_MODALITY,
    alias: str | None = None,
) -> ResolvedHubModel | None:
    """从投影解析一个明文模型。

    - 指定 alias：按 alias 匹配；
    - 否则：该模态下 ``is_default``（首个 primary）优先，再取第一个。
    无投影 / 无匹配 / 无信封 key 时返回 None（调用方回退 synthetic/env）。
    """
    projection = load_projection()
    if projection is None:
        return None
    from app.core.model_registry import crypto

    candidates = [m for m in projection.models if modality in m.modalities]
    record: HubModelRecord | None = None
    if alias is not None:
        record = next((m for m in candidates if m.alias == alias), None)
    if record is None:
        record = next((m for m in candidates if m.is_default), None)
    if record is None:
        record = candidates[0] if candidates else None
    if record is None or not record.api_key_enc:
        return None
    try:
        api_key = crypto.decrypt(record.api_key_enc.encode("ascii"))
    except (crypto.DecryptionFailed, ValueError) as exc:
        logger.warning("hub model key decrypt failed: %s", exc)
        return None
    pricing = record.pricing or {}
    input_price = float(pricing.get("input_usd_per_million", 0) or 0)
    output_price = float(pricing.get("output_usd_per_million", 0) or 0)
    daily_budget = (
        record.daily_budget_micros / 1_000_000
        if record.daily_budget_micros is not None
        else None
    )
    return ResolvedHubModel(
        model=record.model,
        api_key=api_key,
        base_url=record.base_url,
        assignment_id=record.assignment_id,
        alias=record.alias,
        provider=record.provider,
        endpoints=record.endpoints,
        modalities=record.modalities,
        input_price_per_1m=input_price,
        output_price_per_1m=output_price,
        daily_budget=daily_budget,
    )


# ---------------- 场景 → alias 统一解析（W6-2） ----------------

#: 场景显式 alias 覆盖；未列出的场景按其 modality 取该模态默认（primary）。
#: 若某场景需要单独的模型，在 hub 分配该 alias 并在此登记。
SCENE_ALIAS: dict[str, str] = {
    # 例："ARTICLE-GEN": "article",
}

#: 场景 → modality 映射（chat 类场景统一为 text）。
SCENE_MODALITY: dict[str, str] = {
    "ATOM-AFFINITY": "embedding",
    "VIDEO-GEN": "video",
}


def scene_modality(scene: str) -> str:
    """推断场景的 modality；默认 text（绝大多数 chat 场景）。"""
    return SCENE_MODALITY.get(scene, "text")


def resolve_for_scene(scene: str, modality: str | None = None) -> ResolvedHubModel | None:
    """统一解析层：按场景（scene 即 alias 语义）从 hub 投影解析明文模型。

    解析顺序：该场景显式 alias（SCENE_ALIAS）→ 该 modality 默认（primary）。
    hub 未配置 / 无投影 / 无匹配时返回 None（调用方回退旧路由/synthetic）。
    """
    mod = modality or scene_modality(scene)
    alias = SCENE_ALIAS.get(scene)
    return resolve_hub_model(mod, alias)


# ---------------- 用量上报（按张/秒/token，W6-3） ----------------


def report_usage(
    *,
    feature: str,
    provider: str,
    model: str,
    assignment_id: str | None = None,
    billing_source: str = "builtin",
    billing_type: str = "payg",
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    quantity: float | None = None,
    http_status: int = 200,
    cached: bool = False,
) -> None:
    """向 hub 上报一次用量（fire-and-forget，失败静默）。

    - 文本：input_tokens/output_tokens；
    - 图片：quantity＝张数；
    - 视频：quantity＝秒数。
    """
    client = get_hub_client()
    if client is None:
        return
    body: dict[str, Any] = {
        "project": HUB_PROJECT_SLUG,
        "feature": feature,
        "billing_source": billing_source,
        "billing_type": billing_type,
        "provider": provider,
        "model": model,
        "http_status": http_status,
        "cached": cached,
        "ts": datetime.now(UTC).isoformat(),
    }
    if assignment_id:
        body["assignment_id"] = assignment_id
    if input_tokens is not None:
        body["input_tokens"] = input_tokens
    if output_tokens is not None:
        body["output_tokens"] = output_tokens
    if quantity is not None:
        body["quantity"] = quantity
    try:
        client.report_usage(body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("report usage failed: %s", exc)
