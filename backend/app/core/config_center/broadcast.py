"""Q135 配置中心多副本缓存失效广播（Redis pub/sub）。

V1（M10 切片 a/c）配置发布只在提交后原子切换**本进程**快照；多副本部署时其余
副本的进程内缓存不会失效。本模块补齐跨进程广播：

- 发布侧：配置事务 ``after_commit`` 后向频道 ``loom:config:invalidate`` PUBLISH
  一条失效消息（payload 为变更 key，全量失效为 ``*``）。广播是 **best-effort**——
  事务既已提交，发布失败只能告警（对端最坏短暂陈旧），绝不让已成功的发布报错；
- 订阅侧：``ConfigBroadcastSubscriber`` 后台任务订阅该频道，收到消息后用独立
  会话重载本进程快照——``*`` 全量 ``reload()``，具体 key 走 Q140 的
  ``reload_keys()`` 单 key 增量失效（DB 已删的 key 同步从快照移除）。
  订阅/轮询/重载异常只告警并继续，任务不自毁；Q140 起断线/故障按指数退避
  （1s 起、封顶 30s）重试，成功一次即重置，避免重连忙等打满 CPU/连接。

门控 ``LOOM_CONFIG_CACHE_BROADCAST_ENABLED`` 默认 false：单副本/本地不接触
Redis，行为与 V1 完全一致。无 PG 迁移。
"""

import asyncio
import contextlib
import logging
import time

import redis
import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.config_center.cache import config_cache

logger = logging.getLogger(__name__)

CONFIG_INVALIDATION_CHANNEL = "loom:config:invalidate"
INVALIDATE_ALL = "*"

# 订阅轮询取不到消息时的等待/故障退避节拍（秒）。
DEFAULT_POLL_TIMEOUT_SECONDS = 1.0
# Q140 连续故障的指数退避：从 1s 起倍增，封顶 30s；成功一次即重置。
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_CAP_SECONDS = 30.0


_client: aioredis.Redis | None = None
_test_client: aioredis.Redis | None = None

# 强引用持有 after_commit 里 fire-and-forget 的发布任务，避免被 GC 提前回收。
_bg_tasks: set[asyncio.Task] = set()


def override_broadcast_client(client: aioredis.Redis | None) -> None:
    """测试注入替身 Redis；传 None 还原懒连接。"""
    global _test_client
    _test_client = client


def _get_client() -> aioredis.Redis:
    global _client
    client = _test_client if _test_client is not None else _client
    if client is None:
        client = aioredis.from_url(get_settings().redis_dsn, decode_responses=True)
        if _test_client is None:
            _client = client
    return client


async def publish_invalidation(client, *, key: str | None = None) -> int:
    """PUBLISH 一条失效消息，返回收到该消息的订阅者数（Redis 原生返回）。"""
    payload = key or INVALIDATE_ALL
    return int(await client.publish(CONFIG_INVALIDATION_CHANNEL, payload))


async def _publish_best_effort(key: str | None) -> None:
    try:
        await publish_invalidation(_get_client(), key=key)
    except Exception:
        # 事务已提交：广播失败不能上抛污染 after_commit，仅告警（对端可能陈旧）。
        logger.exception(
            "publish config invalidation failed; peer replicas may serve stale cache"
        )


def spawn_invalidation(key: str | None = None) -> None:
    """在同步 after_commit 钩子里调度一次 best-effort 广播。

    门控关闭时直接返回、不接触 Redis；无运行中的事件循环（非 async 上下文）时
    只告警不抛。
    """
    if not get_settings().config_cache_broadcast_enabled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.exception("no running event loop; cannot broadcast config invalidation")
        return
    task = loop.create_task(_publish_best_effort(key), name="loom-config-invalidate")
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


class ConfigBroadcastSubscriber:
    """订阅失效频道并在收到消息时全量 reload 本进程配置快照的后台任务。"""

    def __init__(
        self,
        session_factory,
        *,
        poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_cap_seconds: float = DEFAULT_BACKOFF_CAP_SECONDS,
        ttl_seconds: float | None = None,
    ):
        self._factory = session_factory
        self._poll_timeout = poll_timeout_seconds
        self._backoff_base = backoff_base_seconds
        self._backoff_cap = backoff_cap_seconds
        # Q141：None 表示取 settings.config_cache_ttl_seconds（默认 300s）。
        self._ttl = ttl_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._pubsub = None
        # 最近一次成功装载的 monotonic 时间戳（消息 reload 与 TTL 兜底都刷新）。
        self._last_reload_at: float | None = None
        # 可观测/测试：广播触发的 reload 次数、TTL 兜底 reload 次数、
        # 连续故障计数（驱动指数退避）。
        self.reloads = 0
        self.ttl_reloads = 0
        self.consecutive_failures = 0

    def _backoff_delay(self) -> float:
        return min(
            self._backoff_cap,
            self._backoff_base * (2 ** max(0, self.consecutive_failures - 1)),
        )

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        # Q141：继承启动前的装载时刻作为 TTL 计时起点（应用启动通常已全量
        # reload 一次）；为 None 时等首次成功 reload 后才开始周期兜底。
        self._last_reload_at = config_cache.loaded_at
        self._task = asyncio.create_task(self._loop(), name="loom-config-subscriber")

    def _ttl_seconds(self) -> float:
        return self._ttl if self._ttl is not None else get_settings().config_cache_ttl_seconds

    async def _ttl_reload_if_due(self) -> bool:
        """Q141 TTL 兜底：广播丢消息时，超过 TTL 未成功装载则回源全量 reload。

        仅在曾成功装载（``_last_reload_at`` 非 None）后周期触发，给对端最坏
        陈旧时长设上限；从未装载时不主动触发（启动已有全量 reload，也避免无
        factory 的轮询误触）。回源异常由 ``poll_once`` 的统一 except 捕获退避。
        """
        last = self._last_reload_at
        if last is None or time.monotonic() - last < self._ttl_seconds():
            return False
        async with self._factory() as session:
            await config_cache.reload(session)
        self._last_reload_at = time.monotonic()
        self.ttl_reloads += 1
        logger.info("config cache reloaded by TTL safety net")
        return True

    async def _ensure_pubsub(self):
        if self._pubsub is None:
            client = _get_client()
            self._pubsub = client.pubsub()
            await self._pubsub.subscribe(CONFIG_INVALIDATION_CHANNEL)
        return self._pubsub

    async def poll_once(self) -> bool:
        """取并处理一条失效消息；有消息且 reload 成功返回 True，无消息/故障返回 False。

        Redis 故障或 reload 异常只告警返回 False（循环下一轮自愈/重试），
        CancelledError 不在此拦截（保证 stop 能取消）。
        """
        try:
            pubsub = await self._ensure_pubsub()
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=self._poll_timeout
            )
            if message is None:
                # 连接健康、只是暂无消息：重置退避；Q141 再做 TTL 兜底回源。
                self.consecutive_failures = 0
                return await self._ttl_reload_if_due()
            # payload 为变更 key 或 '*'：'*'/缺失全量 reload，具体 key 增量失效。
            raw = message.get("data")
            key = (
                raw.decode() if isinstance(raw, bytes) else (None if raw is None else str(raw))
            )
            async with self._factory() as session:
                if not key or key == INVALIDATE_ALL:
                    await config_cache.reload(session)
                else:
                    await config_cache.reload_keys(session, [key])
            self.reloads += 1
            self.consecutive_failures = 0
            self._last_reload_at = time.monotonic()
            logger.info(
                "config cache %s from invalidation broadcast",
                "reloaded" if not key or key == INVALIDATE_ALL else f"reloaded key {key}",
            )
            return True
        except asyncio.CancelledError:
            raise
        except redis.RedisError:
            # 订阅连接故障：丢弃 pubsub，下一轮懒重建连，任务不自毁；计入退避。
            self.consecutive_failures += 1
            logger.exception(
                "config broadcast poll failed (streak=%s); will resubscribe",
                self.consecutive_failures,
            )
            await self._close_pubsub()
            return False
        except Exception:
            self.consecutive_failures += 1
            logger.exception(
                "config invalidation reload failed (streak=%s); will retry",
                self.consecutive_failures,
            )
            return False

    async def _loop(self) -> None:
        while not self._stop.is_set():
            await self.poll_once()
            if self._stop.is_set():
                break
            if self.consecutive_failures:
                # Q140：连续故障指数退避，避免重连忙等；stop 可立即唤醒退出。
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self._backoff_delay()
                    )
                except TimeoutError:
                    pass
            else:
                # 零拍让出：真 Redis 的 get_message(timeout=) 自身会阻塞 poll_timeout，
                # 但替身/立即返回路径不阻塞，必须每轮让出一次以免忙转饿死定时器。
                await asyncio.sleep(0)

    async def _close_pubsub(self) -> None:
        if self._pubsub is None:
            return
        with contextlib.suppress(Exception):
            close = getattr(self._pubsub, "aclose", None) or getattr(
                self._pubsub, "close", None
            )
            if close is not None:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
        self._pubsub = None

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._close_pubsub()
