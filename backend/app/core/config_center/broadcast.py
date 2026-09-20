"""Q135 配置中心多副本缓存失效广播（Redis pub/sub）。

V1（M10 切片 a/c）配置发布只在提交后原子切换**本进程**快照；多副本部署时其余
副本的进程内缓存不会失效。本模块补齐跨进程广播：

- 发布侧：配置事务 ``after_commit`` 后向频道 ``loom:config:invalidate`` PUBLISH
  一条失效消息（payload 为变更 key，全量失效为 ``*``）。广播是 **best-effort**——
  事务既已提交，发布失败只能告警（对端最坏短暂陈旧），绝不让已成功的发布报错；
- 订阅侧：``ConfigBroadcastSubscriber`` 后台任务订阅该频道，收到消息后用独立
  会话 ``config_cache.reload()`` 全量重载（配置项规模小，全量重载最简单可靠；
  单 key 热更的一致性优化随 V2）。订阅/轮询/重载异常只告警并继续，任务不自毁。

门控 ``LOOM_CONFIG_CACHE_BROADCAST_ENABLED`` 默认 false：单副本/本地不接触
Redis，行为与 V1 完全一致。无 PG 迁移。
"""

import asyncio
import contextlib
import logging

import redis
import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.config_center.cache import config_cache

logger = logging.getLogger(__name__)

CONFIG_INVALIDATION_CHANNEL = "loom:config:invalidate"
INVALIDATE_ALL = "*"

# 订阅轮询取不到消息时的等待/故障退避节拍（秒）。
DEFAULT_POLL_TIMEOUT_SECONDS = 1.0


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
    ):
        self._factory = session_factory
        self._poll_timeout = poll_timeout_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._pubsub = None
        # 可观测/测试：成功 reload 次数。
        self.reloads = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="loom-config-subscriber")

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
                return False
            # payload 为变更 key 或 '*'；V1 统一全量 reload（配置项少、避免单键
            # 热更与版本错位），消息本身只作为"配置已变更"的触发信号。
            async with self._factory() as session:
                await config_cache.reload(session)
            self.reloads += 1
            logger.info("config cache reloaded from invalidation broadcast")
            return True
        except asyncio.CancelledError:
            raise
        except redis.RedisError:
            # 订阅连接故障：丢弃 pubsub，下一轮懒重建连，任务不自毁。
            logger.exception("config broadcast poll failed; will resubscribe")
            await self._close_pubsub()
            return False
        except Exception:
            logger.exception("config invalidation reload failed; will retry")
            return False

    async def _loop(self) -> None:
        while not self._stop.is_set():
            handled = await self.poll_once()
            if not handled and self._pubsub is not None:
                # get_message(timeout=) 自身已等待；仅在重建连接等无等待路径补节拍。
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
