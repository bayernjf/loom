"""Q89 Redis leader 锁原语（SET NX PX + owner token + Lua 安全释放/续约）。

Q133（C1.77）补 fencing token：每次抢锁成功由 Redis INCR 取一把按锁名全局
单调递增的整数令牌（fence），随 LockLease 暴露给持锁方；看门狗若发现锁在一轮
作业中途过期易主，除留错误日志外把 lease 置为 lost，长轮作业可用
``raise_if_lost()`` / ``wait_lost()`` 协作式中止，旧持有者不再写下游。需要强
fencing 的下游写者在受保护游标行携带 fence 做条件更新（``WHERE fence < :token``），
旧持有者的迟到写入被拒——该 DB 侧条件更新随具体 V2 写者接入，本模块只发令牌。

V1 单副本默认关闭（``LOOM_DISTRIBUTED_LOCK_ENABLED=false``），不接触 Redis、
不改变两个循环既有行为；开启后获取/取令牌任一 Redis 故障一律 fail-closed。
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator

import redis
import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.metrics.business import record_lock_lost

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


def _fence_key(name: str) -> str:
    # 单调序列长期保留、不设 TTL：TTL 回绕会破坏 fencing 单调性。
    return f"loom:fence:{name}"


class LockUnavailable(Exception):
    """锁已被其他副本持有（本副本应跳过本轮；HTTP 口径 409）。"""


class LockBackendError(Exception):
    """Redis 故障（fail-closed：跳过本轮；HTTP 口径 503）。"""


class LockLost(Exception):
    """持锁期间锁已过期并易主（fencing 违例）；长轮作业应协作式中止本轮。"""


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


class LockLease:
    """一次持锁租约。

    - ``fence``：本次持锁的单调递增令牌（未开启锁时为 None）。每次锁易主
      INCR 递增一次，下游据此拒绝旧持有者的迟到写入。
    - ``held``：租约是否仍确认在握。看门狗续约发现锁易主后置 False。
    """

    def __init__(self, name: str, *, owner_token: str | None, fence: int | None):
        self.name = name
        self.owner_token = owner_token
        self.fence = fence
        self._lost = asyncio.Event()

    @property
    def held(self) -> bool:
        return not self._lost.is_set()

    def __bool__(self) -> bool:
        return self.held

    def _mark_lost(self) -> None:
        # Q188：看门狗判丢的唯一漏斗（锁易主与续约故障两条分支都走这里），
        # 在此计数而不是在四个 catch 站点各计一次——那会把一次易主数成多次。
        record_lock_lost(self.name)
        self._lost.set()

    async def wait_lost(self) -> None:
        """阻塞到租约丢失（未开启锁或租约正常期间一直挂起）。"""
        await self._lost.wait()

    def raise_if_lost(self) -> None:
        """长轮作业在关键步骤前调用：锁已易主则抛 LockLost 中止本轮。"""
        if not self.held:
            raise LockLost(self.name)


@contextlib.asynccontextmanager
async def leader_lease(
    name: str, *, ttl_seconds: float = DEFAULT_TTL_SECONDS
) -> AsyncIterator[LockLease]:
    """循环级单实例锁，返回带 fencing token 的租约（Q133）。

    未开启多副本锁时直接放行（返回 fence=None、恒 held 的空租约，不接触 Redis）；
    开启后抢锁失败抛 LockUnavailable，抢锁/取令牌/续约期 Redis 故障抛
    LockBackendError（fail-closed）。租约中途易主不抛异常，而是把 lease 置 lost，
    由持锁方在关键步骤 ``raise_if_lost()`` 协作式中止。
    """
    if not get_settings().distributed_lock_enabled:
        yield LockLease(name, owner_token=None, fence=None)
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

    # 抢锁成功后取单调 fence；INCR 失败属 Redis 故障：释放刚取得的锁并 fail-closed，
    # 绝不持一把没有单调令牌的锁进入下游。
    try:
        fence = int(await client.incr(_fence_key(name)))
    except redis.RedisError as exc:
        with contextlib.suppress(redis.RedisError):
            await client.eval(_RELEASE_LUA, 1, name, token)
        raise LockBackendError(f"cannot allocate fence token {name}: {exc}") from exc

    lease = LockLease(name, owner_token=token, fence=fence)
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
                    # 锁已过期并易主：置 lost 让持锁方协作式中止（Q133 fencing），
                    # 同时留错误痕迹；不强行打断进行中的一轮。
                    lease._mark_lost()
                    logger.error("leader lock %s lost before tick finished", name)
                    return
            except redis.RedisError:
                # 续约期 Redis 故障无法确认仍持锁：同样置 lost（fail-closed）。
                lease._mark_lost()
                logger.exception("leader lock %s renewal failed", name)
                return

    renew_task = asyncio.create_task(_renew(), name=f"loom-lock-renew-{name}")
    try:
        yield lease
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


@contextlib.asynccontextmanager
async def leader_lock(
    name: str, *, ttl_seconds: float = DEFAULT_TTL_SECONDS
) -> AsyncIterator[bool]:
    """循环级单实例锁（Q89 布尔语义，保持向后兼容）。

    与 ``leader_lease`` 共用同一套获取/看门狗/fencing 机制，仅把租约折叠为布尔：
    未开启锁 yield False（不接触 Redis），开启并持锁 yield True。租约中途易主
    维持 Q89 口径（记录日志、不打断本轮）；需要 fencing/协作式中止的写者改用
    ``leader_lease``。
    """
    if not get_settings().distributed_lock_enabled:
        yield False
        return
    async with leader_lease(name, ttl_seconds=ttl_seconds) as lease:
        yield lease.held
