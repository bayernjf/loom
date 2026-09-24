"""Q188：业务级指标（docs/20 §6.5 R1 收口）。

四类此前「有事实、无指标」的信号在此登记：作业失败 / 队列积压 / 锁易主 /
LLM 日预算与上游延迟。本模块**只定义序列与写入助手**，不新建循环、不新增
查询——每个指标都挂在它真实的产出点上：

- ``loom_job_failed_total``   各域 service 把 job 行写成 failed 的那一刻；
- ``loom_stream_dead_letters_total`` / ``loom_stream_*``  在 Q134 Streams 原语里；
- ``loom_lock_lost_total``    租约看门狗判丢（``LockLease._mark_lost``）；
- ``loom_llm_*``              模型网关的预算硬停与驱动往返。

刻意不打 tenant / model_id 标签：这两类取值基数无上界，会把抓取面变成日志。
"""
from __future__ import annotations

from time import perf_counter

from app.core.metrics.middleware import REGISTRY
from app.core.metrics.registry import Counter, Gauge, Histogram

# LLM 上游往返的量级是秒到分钟：DEFAULT_BUCKETS 最大 10s，真供应商调用会整批
# 落 +Inf，P99 分位就失去意义，故这里显式放宽。
LLM_BUCKETS: tuple[float, ...] = (1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0)

JOBS_FAILED = Counter(
    "loom_job_failed_total",
    "Async jobs driven to a failed terminal state, by kind.",
    ("kind",),
)
STREAM_DEAD_LETTERS = Counter(
    "loom_stream_dead_letters_total",
    "Stream entries moved to the dead-letter stream, by origin stream.",
    ("stream",),
)
STREAM_PENDING = Gauge(
    "loom_stream_pending",
    "Delivered-but-unacknowledged entries in a consumer group (XPENDING).",
    ("stream", "group"),
)
STREAM_LENGTH = Gauge(
    "loom_stream_length",
    "Entries held by a stream (XLEN); near MAXLEN the cap starts trimming.",
    ("stream",),
)
LOCK_LOST = Counter(
    "loom_lock_lost_total",
    "Leader leases marked lost by the watchdog (takeover or renew failure).",
    ("lock",),
)
LLM_BUDGET_BLOCKED = Counter(
    "loom_llm_budget_blocked_total",
    "Model calls refused by the daily budget hard stop, by scene.",
    ("scene",),
)
LLM_UPSTREAM_DURATION = Histogram(
    "loom_llm_upstream_duration_seconds",
    "Round-trip duration of a driver call to a model provider.",
    ("scene", "provider", "outcome"),
    buckets=LLM_BUCKETS,
)

for _metric in (
    JOBS_FAILED,
    STREAM_DEAD_LETTERS,
    STREAM_PENDING,
    STREAM_LENGTH,
    LOCK_LOST,
    LLM_BUDGET_BLOCKED,
    LLM_UPSTREAM_DURATION,
):
    REGISTRY.register(_metric)


def record_job_failed(kind: str) -> None:
    """作业进入 failed 终态时计一次。

    口径已知偏差：计数发生在 service 写点、**调用方 commit 之前**（这些函数按
    Q187 同款契约「不自行提交」）。故若那条 commit 本身失败，本进程会多计一次。
    刻意不在六个调用方各自 commit 后补计——那会丢掉「唯一漏斗」性质、更容易漏点；
    且该场景意味着写库自身故障，`LoomJobFailed`（warning）报出来仍是有意义的事实。
    """
    JOBS_FAILED.inc(kind=kind)


def record_dead_letter(stream: str) -> None:
    STREAM_DEAD_LETTERS.inc(stream=stream)


def record_lock_lost(lock: str) -> None:
    LOCK_LOST.inc(lock=lock)


def record_budget_blocked(scene: str) -> None:
    LLM_BUDGET_BLOCKED.inc(scene=scene)


def set_stream_depth(stream: str, group: str, pending: int, length: int) -> None:
    STREAM_PENDING.set(float(pending), stream=stream, group=group)
    STREAM_LENGTH.set(float(length), stream=stream)


async def observe_llm_call(scene: str, provider: str, awaitable):
    """计时一次驱动往返并如实标注成败，不改变异常语义（失败照原样抛出）。"""
    start = perf_counter()
    outcome = "error"
    try:
        result = await awaitable
        outcome = "ok"
        return result
    finally:
        LLM_UPSTREAM_DURATION.observe(
            perf_counter() - start, scene=scene, provider=provider, outcome=outcome
        )
