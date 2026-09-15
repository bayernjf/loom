"""Q89 多副本单实例锁：Redis SET NX PX 分布式 leader 锁。

口径（02 C1.33 四接缝，均为负责人拍板推荐项甲案）：

1. 机制：Redis SET key token NX PX ttl；唯一 owner token，释放/续约走 Lua
   比对 token（不删别人的锁）；持锁期间看门狗按 TTL/3 周期续约，进程崩溃
   则 TTL 到期自动释放。
2. 粒度：循环级两把命名锁（sla-sweep / restock-worker），持锁副本才跑该轮；
   不做每信号行细粒度认领（append-only 认领逻辑一字不改）。
3. 门控：LOOM_DISTRIBUTED_LOCK_ENABLED 默认 false（单副本/本地无 Redis 依赖）；
   开启后 Redis 故障一律 fail-closed——跳过本轮并报错日志，绝不无锁双跑。
4. 手工触发端点（/api/admin/sla/run、/api/admin/restock/run）抢同一把锁，
   抢不到 409。
"""

from .service import (
    RESTOCK_LOCK,
    SWEEP_LOCK,
    LockBackendError,
    LockUnavailable,
    leader_lock,
    override_lock_client,
)

__all__ = [
    "RESTOCK_LOCK",
    "SWEEP_LOCK",
    "LockBackendError",
    "LockUnavailable",
    "leader_lock",
    "override_lock_client",
]
