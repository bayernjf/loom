"""Q188：业务级指标单元测试（信号产出点与助手行为）。

REGISTRY 是进程全局、跨用例累积，所以所有断言都取**同标签样本的前后增量**，
不假设初值为 0——否则单跑绿、全量跑红。
"""

import math
import pathlib

import pytest
import redis

from app.core.exports import service as exports_service
from app.core.locking import RESTOCK_LOCK, SWEEP_LOCK
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


# ---------------------------------------------------------------------------
# Q193：首次事件必须可告警（懒创建 counter 首个样本非零 = 对 increase() 永久不可见）
# ---------------------------------------------------------------------------

APP_ROOT = pathlib.Path(__file__).resolve().parents[2] / "app"


def _exposition_has(text: str, line: str) -> bool:
    return line in text


def test_every_required_label_combination_is_primed() -> None:
    """可静态枚举的标签组合必须在 import 后就有 0 值序列，否则首事件不可告警。

    只断言"必备组合都在"：REGISTRY 进程全局，同文件其它用例会往同一批序列上累加，
    所以既不断言"仅有这些"、也不断言取值，否则必然随执行顺序翻红。

    场景维度的预置由模型网关在 import 时完成（场景词表归它所有），故这里显式 import
    gateway 声明前提——生产进程经 app.main 必然走到它，但守卫不该赌偶然导入链。
    """
    from app.core.model_registry import gateway  # noqa: F401  (场景零序列在此登记)
    from app.core.model_registry.seeds import all_scene_codes

    kinds = {key[0][1] for key in business.JOBS_FAILED._samples}
    scenes = {key[0][1] for key in business.LLM_BUDGET_BLOCKED._samples}
    locks = {key[0][1] for key in business.LOCK_LOST._samples}
    assert set(business.JOB_KINDS) <= kinds, f"未预置的 kind 首事件不可见: {set(business.JOB_KINDS) - kinds}"
    assert set(all_scene_codes()) <= scenes, f"未预置的场景: {set(all_scene_codes()) - scenes}"
    assert {SWEEP_LOCK, RESTOCK_LOCK} <= locks, f"未预置的锁: {{SWEEP_LOCK, RESTOCK_LOCK}} - {locks}"


def test_first_event_is_visible_as_a_zero_to_one_transition_in_the_exposition() -> None:
    """直接验 Prometheus 真正依赖的性质：同一序列在抓取文本里先是 0、事件后是 1。

    用一个本用例自己新建的标签组合，避开其它用例已累加过的序列。
    """
    from app.core.metrics.middleware import REGISTRY

    probe = "loom:lock:test-alertability"
    business.prime_lock_lost(probe)
    zero_line = 'loom_lock_lost_total{lock="' + probe + '"} 0'
    one_line = 'loom_lock_lost_total{lock="' + probe + '"} 1'
    assert _exposition_has(REGISTRY.render(), zero_line), "首发前必须已有 0 序列"
    business.record_lock_lost(probe)
    assert _exposition_has(REGISTRY.render(), one_line), "首发后应翻成 1，increase() 才看得见"


@pytest.mark.asyncio
async def test_worker_tick_primes_the_dead_letter_series_it_consumes() -> None:
    """死信只有在本流真被消费时才可能产生，故随 tick 取样一起预置。"""
    stream, group = "loom:stream:prime-check", "g"
    key = business.STREAM_DEAD_LETTERS._key({"stream": stream})
    assert key not in business.STREAM_DEAD_LETTERS._samples
    # 即便取样因后端故障失败，预置也已先完成——首条死信不该因一次抓取抖动而不可见。
    assert await sample_stream_depth(FakeStreamsRedis(fail=True), stream, group) is False
    assert key in business.STREAM_DEAD_LETTERS._samples
    assert business.STREAM_DEAD_LETTERS._samples[key] == 0.0


def test_job_failure_kinds_in_code_are_exactly_the_primed_set() -> None:
    """漂移守卫：服务里出现的 kind 字面量必须都在已预置的 JOB_KINDS 内。"""
    import re

    used = set()
    for path in APP_ROOT.rglob("*.py"):
        used.update(re.findall(r'record_job_failed\("([^"]+)"\)', path.read_text()))
    assert used, "no record_job_failed call found - the guard stopped matching"
    assert used <= set(business.JOB_KINDS), f"unprimed kind(s) would be alert-blind: {used - set(business.JOB_KINDS)}"


def test_scene_code_helper_tracks_the_constants() -> None:
    """all_scene_codes 靠 SCENE_ 前缀扫描；改名或漏前缀就会静默漏预置。"""
    from app.core.model_registry import seeds

    declared = {
        value
        for name, value in vars(seeds).items()
        if name.startswith("SCENE_") and isinstance(value, str)
    }
    assert set(seeds.all_scene_codes()) == declared
