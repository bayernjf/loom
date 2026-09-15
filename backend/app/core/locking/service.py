"""Q89 Redis leader 锁原语（SET NX PX + owner token + Lua 安全释放/续约）。"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator

import redis
import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SWEEP_LOCK = "loom:lock:sla-sweep"
RESTOCK_LOCK = "loom:lock:restock-worker"

DEFAULT_TTL_SECONDS = 60.0

# 仅当持有者 token 匹配才动作，避免误删/误续别人的锁（TTL 过期换主场景）。
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)
_RENEW_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"
)


class LockUnavailable(Exception):
    """锁已被其他副本持有（本副本应跳过本轮；HTTP 口径 409）。"""


class LockBackendError(Exception):
    """Redis 故障（fail-closed：跳过本轮；HTTP 口径 503）。"""


_client: aioredis.Redis | None = None
_test_client: aioredis.Redis | None = None


def override_lock_client(client: aioredis.Redis | None) -> None:
    """测试注入替身 Redis；传 None 还原懒连接。"""
    global _test_client
    _test_client = client


def _get_client() -> aioredis.Redis:
    global _client
    client = _test_client if _test_client is not None else _client
    if client is None:
        client = aioredis.from_url(get_settings().redis_dsn)
        if _test_client is None:
            _client = client
    return client


@contextlib.asynccontextmanager
async def leader_lock(
    name: str, *, ttl_seconds: float = DEFAULT_TTL_SECONDS
) -> AsyncIterator[bool]:
    """循环级单实例锁。

    未开启多副本锁时直接放行（yield False，不接触 Redis）；开启后抢锁失败
    抛 LockUnavailable，Redis 故障抛 LockBackendError，调用方负责跳过/映射。
    """
    if not get_settings().distributed_lock_enabled:
        yield False
        return

    client = _get_client()
    token = uuid.uuid4().hex
    ttl_ms = max(1, int(ttl_seconds * 1000))
    try:
        acquired = await client.set(name, token, nx=True, px=ttl_ms)
    except redis.RedisError as exc:
        raise LockBackendError(f"cannot acquire lock {name}: {exc}") from exc
    if not acquired:
        raise LockUnavailable(name)

    stop = asyncio.Event()

    async def _renew() -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=ttl_seconds / 3)
                return
            except TimeoutError:
                pass
            try:
                renewed = await client.eval(_RENEW_LUA, 1, name, token, ttl_ms)
                if not renewed:
                    # 锁已过期并易主：本副本不再持锁。fencing 退场留 V2，
                    # 此处只留错误痕迹，不打断进行中的一轮。
                    logger.error("leader lock %s lost before tick finished", name)
                    return
            except redis.RedisError:
                logger.exception("leader lock %s renewal failed", name)
                return

    renew_task = asyncio.create_task(_renew(), name=f"loom-lock-renew-{name}")
    try:
        yield True
    finally:
        stop.set()
        renew_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renew_task
        try:
            await client.eval(_RELEASE_LUA, 1, name, token)
        except redis.RedisError:
            # 释放失败靠 TTL 兜底，不影响业务结果。
            logger.exception("leader lock %s release failed", name)
