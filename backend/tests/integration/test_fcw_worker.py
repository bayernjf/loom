"""Q165 FCW 批量组装异步 worker 集成测试（内存 SQLite + FakeStreamsRedis，无真 Redis）。

镜像 Q137/Q161 worker 测试范式，重点覆盖：
- 门控关：POST 同步跑完（V1 行为回归）；
- 门控开：建 queued 入流、不立即组装；
- worker 消费 queued→completed 并 ACK；幂等重复投递不重处理；
- per-slot Guard/重复发证失败隔离记 results.failures，任务整体 completed；
- 幽灵 task_id 直接 ACK 丢弃；入流失败 fail-closed 无残留；
- 基础设施异常留 PEL、超 MAX_DELIVERIES 进死信并置 failed；
- 七 Guard 审计（fcw.assembly_blocked）在 worker 路径完整落库。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.actor import Actor
from app.core.config import get_settings
from app.core.db import Base, get_session
from app.core.metrics.business import JOBS_FAILED, STREAM_DEAD_LETTERS, STREAM_PENDING
from app.core.models import AuditLog
from app.core.queue import (
    add_event,
    ensure_group,
    override_stream_client,
    read_new,
)
from app.core.queue import streams as streams_mod
from app.core.staff_auth.deps import get_auth_session
from app.final.fcw_worker.worker import FcwWorker
from app.final.final_whitelist import service
from app.final.final_whitelist.models import FcwAssemblyTask, FinalContentWhitelist
from app.final.final_whitelist.schemas import AssemblyTaskCreate
from app.main import app
from app.platform.platform_adaptation.models import GoalFitWeight, PcpTemplate
from app.platform.platform_adaptation.seeds import (
    FIT_WEIGHT_SEEDS,
    PCP_TEMPLATE_SEEDS,
)
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import G2Field
from tests.integration.staff_tokens import bearer, issue_staff_token
from tests.integration.stream_fakes import FakeStreamsRedis
from tests.integration.test_fcw_api import (
    COMPLIANCE,
    GOAL,
    OPS,
    PLATFORM,
    _freeze,
    _make_ps,
    _seed_static_inputs,
)
from tests.metric_reads import counter_value, gauge_value

ACTOR = Actor(**OPS)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    # Q203：E1.1 写口在门控关下也自行验真，走 get_auth_session 这条缝。
    app.dependency_overrides[get_auth_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async with session_factory() as session:
        session.add_all(
            [G2Field(fid="f_a", cat="common", field_name="字段A"),
             G2Field(fid="f_b", cat="selling", field_name="字段B"),
             FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
             FPSourceRoute(route="compliance_risk", name="合规风险面", sort_order=2)]
            + [ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS]
        )
        for seed in FIT_WEIGHT_SEEDS:
            session.add(GoalFitWeight(goal=seed["goal"], weights=seed["weights"]))
        for tpl in PCP_TEMPLATE_SEEDS:
            session.add(
                PcpTemplate(
                    template_id=tpl["template_id"],
                    code=tpl["code"],
                    name=tpl["name"],
                    weights=tpl["weights"],
                )
            )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Q203 #34：发证写口只认已验真令牌，本文件要发证，故默认带一枚 operations 令牌
        # （引导口径同 Q178 上线流程；细节见 tests/integration/staff_tokens.py）。
        ac.headers.update(
            bearer(await issue_staff_token(ac, ["operations"]))
        )
        yield ac


@pytest_asyncio.fixture
def fake():
    redis_client = FakeStreamsRedis()
    override_stream_client(redis_client)
    yield redis_client
    override_stream_client(None)


async def _green_pipeline(client, session_factory, *, slots=1):
    """建一条全绿链（PS→冻结→1 个发布位+PCP+三包→CCR clean），返回 (ps_id, [slot_ids])。"""
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_ids = [await _seed_static_inputs(client, ps_id)]
    extra = [
        await client.post(
            "/api/admin/publish-slots",
            json={"item": {
                "platform": PLATFORM, "code": f"xs-extra-{i}", "name": f"位{i}",
                "slot_type": "short_video", "traffic": 60, "safe": 60,
                "conv": 60, "load": 60,
            }, "actor": OPS},
        )
        for i in range(1, slots)
    ]
    slot_ids.extend(r.json()["slot_id"] for r in extra)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    return ps_id, slot_ids


def _task_body(ps_id, slot_ids, **kw):
    return AssemblyTaskCreate(
        product_space_id=ps_id,
        platform=PLATFORM,
        goal=GOAL,
        count=len(slot_ids),
        slot_ids=slot_ids,
        actor=ACTOR,
        **kw,
    )


def _pel(fake) -> dict:
    return fake.groups[(service.FCW_STREAM, service.FCW_GROUP)]["pel"]


async def _count_fcw(session, ps_id) -> int:
    return len(
        (await session.scalars(
            select(FinalContentWhitelist).where(
                FinalContentWhitelist.product_space_id == ps_id
            )
        )).all()
    )


# ---------- 门控关：V1 同步行为回归 ----------

async def test_gate_off_sync_runs_to_completed(client, session_factory):
    ps_id, slots = await _green_pipeline(client, session_factory, slots=1)
    async with session_factory() as session:
        task = await service.create_task(session, _task_body(ps_id, slots))
        await session.commit()
    assert task.status == service.TASK_STATUS_COMPLETED
    assert len(task.results["issued"]) == 1
    assert task.results["failures"] == []
    async with session_factory() as session:
        assert await _count_fcw(session, ps_id) == 1


# ---------- 门控开：建 queued 入流 ----------

async def test_gate_on_creates_queued_without_assembly(client, session_factory, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "fcw_worker_enabled", True)
    ps_id, slots = await _green_pipeline(client, session_factory, slots=1)
    resp = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 1, "slot_ids": slots, "actor": OPS,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == service.TASK_STATUS_QUEUED
    # 未立即组装：无 final_id 产出。
    async with session_factory() as session:
        assert await _count_fcw(session, ps_id) == 0
        task = await service.get_task(session, body["task_id"])
        assert task.status == service.TASK_STATUS_QUEUED
    # 已入流。
    assert service.FCW_STREAM in fake.streams


async def test_worker_consumes_queued_task_to_completed(client, session_factory, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "fcw_worker_enabled", True)
    ps_id, slots = await _green_pipeline(client, session_factory, slots=1)
    resp = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 1, "slot_ids": slots, "actor": OPS,
        },
    )
    task_id = resp.json()["task_id"]

    worker = FcwWorker(session_factory, block_ms=0)
    await worker._tick()

    async with session_factory() as session:
        task = await service.get_task(session, task_id)
        assert task.status == service.TASK_STATUS_COMPLETED
        assert len(task.results["issued"]) == 1
        assert task.completed_at is not None
        assert await _count_fcw(session, ps_id) == 1
    assert worker.completed == 1
    assert _pel(fake) == {}  # 成功即 ACK


async def test_status_transitions_queued_to_running_to_completed(
    client, session_factory, fake, monkeypatch
):
    monkeypatch.setattr(get_settings(), "fcw_worker_enabled", True)
    ps_id, slots = await _green_pipeline(client, session_factory, slots=1)
    resp = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 1, "slot_ids": slots, "actor": OPS,
        },
    )
    task_id = resp.json()["task_id"]
    # 异步路径创建后 = queued。
    got = await client.get(f"/api/fcw/assembly-tasks/{task_id}")
    assert got.json()["status"] == service.TASK_STATUS_QUEUED

    worker = FcwWorker(session_factory, block_ms=0)
    await worker._tick()
    got = await client.get(f"/api/fcw/assembly-tasks/{task_id}")
    assert got.json()["status"] == service.TASK_STATUS_COMPLETED


# ---------- 幂等 / 隔离 / 幽灵 ----------

async def test_terminal_duplicate_is_acked_without_reprocessing(
    client, session_factory, fake, monkeypatch
):
    monkeypatch.setattr(get_settings(), "fcw_worker_enabled", True)
    ps_id, slots = await _green_pipeline(client, session_factory, slots=1)
    # 先同步跑完该任务，再把它入流（重复投递）。
    async with session_factory() as session:
        task = await service.create_task(session, _task_body(ps_id, slots))
        await session.commit()
        task_id = task.task_id
    await service.enqueue_fcw_task(task_id)

    called = {"n": 0}

    async def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("must not reprocess a terminal task")

    monkeypatch.setattr(service, "process_task", _boom)
    worker = FcwWorker(session_factory, block_ms=0)
    await worker._tick()
    assert called["n"] == 0
    assert _pel(fake) == {}


async def test_per_slot_failure_isolated_task_still_completed(
    client, session_factory, fake, monkeypatch
):
    monkeypatch.setattr(get_settings(), "fcw_worker_enabled", True)
    ps_id, slots = await _green_pipeline(client, session_factory, slots=2)
    # 第一次任务把 slot[0] 发掉。
    async with session_factory() as session:
        await service.create_task(
            session, _task_body(ps_id, [slots[0]])
        )
        await session.commit()
    # 第二次任务跨 [已发 slot0, 未发 slot1]：slot0 重复发证失败隔离，slot1 正常发。
    resp = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 2, "slot_ids": slots, "actor": OPS,
        },
    )
    task_id = resp.json()["task_id"]
    worker = FcwWorker(session_factory, block_ms=0)
    await worker._tick()

    async with session_factory() as session:
        task = await service.get_task(session, task_id)
        assert task.status == service.TASK_STATUS_COMPLETED
        issued = {i["slot_id"] for i in task.results["issued"]}
        failed = {f["slot_id"] for f in task.results["failures"]}
        assert issued == {slots[1]}
        assert failed == {slots[0]}
        assert await _count_fcw(session, ps_id) == 2


async def test_unknown_task_is_acked_discard(session_factory, fake):
    c = streams_mod._get_client()
    await ensure_group(c, service.FCW_STREAM, service.FCW_GROUP)
    await add_event(c, service.FCW_STREAM, {"task_id": "ghost"})

    worker = FcwWorker(session_factory, block_ms=0)
    await worker._tick()
    assert _pel(fake) == {}  # 直接 ACK 丢弃，不崩溃


# ---------- 入流失败 fail-closed ----------

async def test_enqueue_failure_fail_closed_no_residue(
    client, session_factory, fake, monkeypatch
):
    monkeypatch.setattr(get_settings(), "fcw_worker_enabled", True)
    ps_id, slots = await _green_pipeline(client, session_factory, slots=1)
    fake.fail = True  # XADD 抛 RedisError → StreamBackendError
    resp = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 1, "slot_ids": slots, "actor": OPS,
        },
    )
    assert resp.status_code == 503, resp.text
    # 无 task 残留（router 已 delete + commit）。
    async with session_factory() as session:
        rows = (await session.scalars(select(FcwAssemblyTask))).all()
        assert rows == []


# ---------- 基础设施异常：PEL / 死信 ----------

async def test_infra_failure_under_limit_stays_in_pel(
    client, session_factory, fake, monkeypatch
):
    monkeypatch.setattr(get_settings(), "fcw_worker_enabled", True)
    ps_id, slots = await _green_pipeline(client, session_factory, slots=1)
    resp = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 1, "slot_ids": slots, "actor": OPS,
        },
    )
    task_id = resp.json()["task_id"]

    async def _boom(*_a, **_k):
        raise RuntimeError("database down")

    monkeypatch.setattr(service, "process_task", _boom)
    worker = FcwWorker(session_factory, block_ms=0)
    await worker._tick()  # delivery=1 未超限：留 PEL
    assert len(_pel(fake)) == 1
    async with session_factory() as session:
        task = await service.get_task(session, task_id)
        assert task.status != service.TASK_STATUS_FAILED


async def test_infra_failure_over_limit_dead_letters_and_fails_task(
    client, session_factory, fake, monkeypatch
):
    monkeypatch.setattr(get_settings(), "fcw_worker_enabled", True)
    ps_id, slots = await _green_pipeline(client, session_factory, slots=1)
    resp = await client.post(
        "/api/fcw/assembly-tasks",
        json={
            "product_space_id": ps_id, "platform": PLATFORM, "goal": GOAL,
            "count": 1, "slot_ids": slots, "actor": OPS,
        },
    )
    task_id = resp.json()["task_id"]

    # 先让一条消息进 PEL（模拟崩溃投递历史）。
    client = streams_mod._get_client()
    await read_new(
        client, service.FCW_STREAM, service.FCW_GROUP, "crashed", count=10
    )

    async def _boom(*_a, **_k):
        raise RuntimeError("database down")

    monkeypatch.setattr(service, "process_task", _boom)
    failed_before = counter_value(JOBS_FAILED, kind="fcw")
    dead_before = counter_value(STREAM_DEAD_LETTERS, stream=service.FCW_STREAM)
    worker = FcwWorker(
        session_factory, block_ms=0, min_idle_ms=0, max_deliveries=1
    )
    await worker._tick()  # reclaim deliveries=2 > max 1 → 死信 + failed
    assert _pel(fake) == {}
    assert service.FCW_DEAD_STREAM in fake.streams
    # Q188：第三个 worker 与导出/导入同口径——进 failed 计一次、进死信计一次，
    # 且 tick 末尾顺带把该流深度写进 Gauge。
    assert counter_value(JOBS_FAILED, kind="fcw") - failed_before == 1
    assert counter_value(STREAM_DEAD_LETTERS, stream=service.FCW_STREAM) - dead_before == 1
    assert gauge_value(
        STREAM_PENDING, stream=service.FCW_STREAM, group=service.FCW_GROUP
    ) == 0
    async with session_factory() as session:
        task = await service.get_task(session, task_id)
        assert task.status == service.TASK_STATUS_FAILED
        assert "database down" in (task.results.get("error") or "")


# ---------- 七 Guard 审计完整 ----------

async def test_worker_path_assembly_blocked_audit_present(
    client, session_factory, fake, monkeypatch
):
    monkeypatch.setattr(get_settings(), "fcw_worker_enabled", True)
    # 只建链，不跑 CCR → Guard②（compliance clear）不绿，assemble_one 抛 GuardsFailed。
    ps_id = await _make_ps(session_factory)
    await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)

    async with session_factory() as session:
        task = await service.create_queued_task(
            session, _task_body(ps_id, [slot_id])
        )
        await session.commit()
        task_id = task.task_id

    await service.enqueue_fcw_task(task_id)
    worker = FcwWorker(session_factory, block_ms=0)
    await worker._tick()

    async with session_factory() as session:
        task = await service.get_task(session, task_id)
        # per-slot Guard 失败隔离：任务整体 completed，无 final_id 产出。
        assert task.status == service.TASK_STATUS_COMPLETED
        assert task.results["issued"] == []
        assert len(task.results["failures"]) == 1
        blocked = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "fcw.assembly_blocked"
                )
            )
        ).all()
    # worker 路径下 fcw.assembly_blocked 审计行随 task 最终 commit 完整落库。
    assert len(blocked) == 1
    assert blocked[0].entity_id == f"{task.pws_id}:{slot_id}"
