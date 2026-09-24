"""Q188：业务级指标单元测试（信号产出点与助手行为）。

REGISTRY 是进程全局、跨用例累积，所以所有断言都取**同标签样本的前后增量**，
不假设初值为 0——否则单跑绿、全量跑红。
"""

import math

import pytest
import redis

from app.core.exports import service as exports_service
from app.core.locking.service import LockLease
from app.core.metrics import business
from app.core.metrics.middleware import REGISTRY
from app.core.queue import (
    StreamBackendError,
    add_event,
    ensure_group,
    move_to_dead,
    sample_stream_depth,
    stream_depth,
)
from tests.integration.stream_fakes import FakeStreamsRedis
from tests.metric_reads import counter_value, gauge_value

BUSINESS_FAMILIES = {
    "loom_job_failed_total": "counter",
    "loom_stream_dead_letters_total": "counter",
    "loom_stream_pending": "gauge",
    "loom_stream_length": "gauge",
    "loom_lock_lost_total": "counter",
    "loom_llm_budget_blocked_total": "counter",
    "loom_llm_upstream_duration_seconds": "histogram",
}



def test_business_families_are_registered_in_the_shared_registry() -> None:
    """七族必须挂在中间件那个同一个 REGISTRY 上，/metrics 才会带出。"""
    for name, kind in BUSINESS_FAMILIES.items():
        metric = REGISTRY._metrics.get(name)
        assert metric is not None, f"{name} not registered"
        assert metric.metric_type == kind


def test_llm_histogram_buckets_span_real_provider_latency() -> None:
    """默认桶上限 10s 会让真供应商调用整批落 +Inf，故显式放宽到 120s。"""
    assert business.LLM_UPSTREAM_DURATION.buckets[0] == 1.0
    assert business.LLM_UPSTREAM_DURATION.buckets[-1] == math.inf
    assert 30.0 in business.LLM_UPSTREAM_DURATION.buckets


def test_record_job_failed_counts_per_kind() -> None:
    before = {k: counter_value(business.JOBS_FAILED, kind=k) for k in ("export", "import", "fcw")}
    business.record_job_failed("export")
    business.record_job_failed("export")
    business.record_job_failed("fcw")
    assert counter_value(business.JOBS_FAILED, kind="export") - before["export"] == 2
    assert counter_value(business.JOBS_FAILED, kind="import") - before["import"] == 0
    assert counter_value(business.JOBS_FAILED, kind="fcw") - before["fcw"] == 1


def test_mark_lost_is_the_single_lock_loss_funnel() -> None:
    """看门狗两条判丢分支都走 _mark_lost，故计数一处即覆盖（catch 站点不重复计）。"""
    lease = LockLease("loom:lock:test-metrics", owner_token="t", fence=1)
    before = counter_value(business.LOCK_LOST, lock="loom:lock:test-metrics")
    assert lease.held
    lease._mark_lost()
    assert not lease.held
    assert counter_value(business.LOCK_LOST, lock="loom:lock:test-metrics") - before == 1
    with pytest.raises(Exception) as raised:
        lease.raise_if_lost()
    assert type(raised.value).__name__ == "LockLost"
    # raise_if_lost 不再计数：一次易主只算一次。
    assert counter_value(business.LOCK_LOST, lock="loom:lock:test-metrics") - before == 1


@pytest.mark.asyncio
async def test_move_to_dead_counts_the_origin_stream() -> None:
    client = FakeStreamsRedis()
    stream, group = exports_service.EXPORT_STREAM, exports_service.EXPORT_GROUP
    await ensure_group(client, stream, group)
    entry_id = await add_event(client, stream, {"job_id": "j1"})
    before = counter_value(business.STREAM_DEAD_LETTERS, stream=stream)

    await move_to_dead(
        client, stream, group, exports_service.EXPORT_DEAD_STREAM,
        entry_id, {"job_id": "j1"}, reason="max-deliveries-exceeded",
    )

    assert counter_value(business.STREAM_DEAD_LETTERS, stream=stream) - before == 1
    # 计的是原流名（按业务流看死因），死信流本身不产该序列。
    assert counter_value(business.STREAM_DEAD_LETTERS, stream=exports_service.EXPORT_DEAD_STREAM) == 0


@pytest.mark.asyncio
async def test_failed_move_to_dead_does_not_count() -> None:
    """写死信这一步就失败（Redis 故障）时不计数，否则重试会双计。"""
    client = FakeStreamsRedis()
    await ensure_group(client, "loom:stream:metric-dead", "g")
    broken = FakeStreamsRedis(fail=True)
    before = counter_value(business.STREAM_DEAD_LETTERS, stream="loom:stream:metric-dead")
    with pytest.raises(StreamBackendError):
        await move_to_dead(
            broken, "loom:stream:metric-dead", "g", "loom:stream:metric-dead:dead",
            "1-0", {"job_id": "j"}, reason="x",
        )
    assert counter_value(business.STREAM_DEAD_LETTERS, stream="loom:stream:metric-dead") - before == 0


@pytest.mark.asyncio
async def test_sample_stream_depth_writes_both_gauges() -> None:
    client = FakeStreamsRedis()
    stream, group = "loom:stream:metric-depth", "g1"
    await client.xadd(stream, {"n": "1"})
    await client.xadd(stream, {"n": "2"})
    await client.xgroup_create(stream, group, id="0", mkstream=True)
    await client.xreadgroup(group, "c1", {stream: ">"}, count=1)

    assert await sample_stream_depth(client, stream, group) is True
    # 一条已投递未 ACK（XPENDING 汇总），两条在流里（XLEN）——且不受 count 截断。
    assert gauge_value(business.STREAM_PENDING, stream=stream, group=group) == 1
    assert gauge_value(business.STREAM_LENGTH, stream=stream) == 2


@pytest.mark.asyncio
async def test_sample_stream_depth_is_inert_on_backend_failure() -> None:
    """纯观测读绝不打扰消费循环：故障返回 False、不上抛、保留上一次的值。"""
    broken = FakeStreamsRedis(fail=True)
    stream, group = "loom:stream:metric-broken", "g1"
    business.set_stream_depth(stream, group, 42, 42)

    assert await sample_stream_depth(broken, stream, group) is False
    assert gauge_value(business.STREAM_PENDING, stream=stream, group=group) == 42


@pytest.mark.asyncio
async def test_stream_depth_wraps_redis_errors_as_backend_failure() -> None:
    """原语本身 fail-closed（同 Q134 口径）；是 sample_* 那层刻意吞掉。"""
    with pytest.raises(StreamBackendError):
        await stream_depth(FakeStreamsRedis(fail=True), "loom:stream:x", "g")


@pytest.mark.asyncio
async def test_observe_llm_call_records_success_and_failure() -> None:
    async def ok():
        return "text"

    async def boom():
        raise redis.RedisError("upstream down")

    ok_key = business.LLM_UPSTREAM_DURATION._key(
        {"scene": "CAT-RECOG", "provider": "synthetic", "outcome": "ok"}
    )
    err_key = business.LLM_UPSTREAM_DURATION._key(
        {"scene": "CAT-RECOG", "provider": "synthetic", "outcome": "error"}
    )
    before_ok = (business.LLM_UPSTREAM_DURATION._samples.get(ok_key) or {}).get("count", 0)
    before_err = (business.LLM_UPSTREAM_DURATION._samples.get(err_key) or {}).get("count", 0)

    assert await business.observe_llm_call("CAT-RECOG", "synthetic", ok()) == "text"
    with pytest.raises(redis.RedisError):
        await business.observe_llm_call("CAT-RECOG", "synthetic", boom())

    assert business.LLM_UPSTREAM_DURATION._samples[ok_key]["count"] - before_ok == 1
    assert business.LLM_UPSTREAM_DURATION._samples[err_key]["count"] - before_err == 1
    # 失败调用也要留耗时——超时正是最该看的那一类。


def test_record_budget_blocked_counts_by_scene() -> None:
    before = counter_value(business.LLM_BUDGET_BLOCKED, scene="PWC-BUILDER")
    business.record_budget_blocked("PWC-BUILDER")
    assert counter_value(business.LLM_BUDGET_BLOCKED, scene="PWC-BUILDER") - before == 1
