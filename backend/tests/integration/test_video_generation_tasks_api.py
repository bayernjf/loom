"""Q354 段12 真视频生成任务集成测试（异步任务 ＋ 逐单人工 Gate，不自动重试）。

钉的是**花钱边界**与**状态机**，不是供应商返回形状（那由
`tests/unit/test_video_drivers.py` 在真实 httpx 栈上验）：

- 门控关 → create/approve/sync 三口一律 409 且**一次外部调用都不发**（reject 不花钱，
  留着让人关掉门控后还能收掉悬着的待审行）；
- `create` 只落待审行，零外部调用（登记≠花钱）；
- `approve` 才提交，且失败**不重投**（调用计数恒为 1）；失败置终态＋开运营待办＋留审计；
- 一条成品同时只允许一个未终结任务（partial unique 在 SQLite/PG 两侧都承重）；
- 日上限（配置中心 `content.video_real_daily_seconds_cap`）超限 409；
- 路由没配到 video 能力模型 → 409，绝不静默退成 synthetic 假数据；
- `completed` 只写任务行，**不回写 `content_products.body`**（段12 入库口径是下一片）；
- 鉴权：写口无令牌 401／角色不足 403，读口缺 actor 422／客户角色 403。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_READY, ContentProduct
from app.content.video_studio import service as vs
from app.content.video_studio.models import (
    VIDEO_TASK_COMPLETED,
    VIDEO_TASK_FAILED,
    VIDEO_TASK_PENDING,
    VIDEO_TASK_REJECTED,
    VIDEO_TASK_SUBMITTED,
    VIDEO_TASK_TIMED_OUT,
)
from app.core.config import get_settings
from app.core.db import Base, get_session
from app.core.model_registry import crypto, video_drivers
from app.core.model_registry.models import AIModel, AIModelKey, AISceneRoute
from app.core.model_registry.seeds import SCENE_VIDEO_GEN
from app.core.models import AuditLog
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from app.product.modeling.models import OpsTodo
from tests.integration.staff_tokens import acting_as, bearer, issue_staff_token

OPS_ROLES = ["operations"]
LIST_PATH = "/api/admin/video-generation-tasks"
READ = {"actor_id": "ops-vid", "roles": "operations"}
PARAMS = {"mode": "text", "prompt": "a red cube turning", "seconds": 4, "size": "720P",
          "aspect_ratio": "16:9"}


def _create_path(content_id: str = "c-vid") -> str:
    return f"/api/admin/content/{content_id}/video-generation-tasks"


def _task_path(task_id: str, action: str = "") -> str:
    return f"{LIST_PATH}/{task_id}{action}"


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
    app.dependency_overrides[get_auth_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed_route(factory) -> None:
    """VIDEO-GEN → active 的 agnes video 模型＋一枚 active 密钥（真调供应商的路由形状）。"""
    async with factory() as session:
        session.add_all(
            [
                ContentProduct(
                    content_id="c-vid",
                    tenant_id="t-vid",
                    product_space_id="ps-vid",
                    final_id="fcw-vid",
                    goal="ENGAGEMENT",
                    platform="x_platform",
                    kind="video",
                    status=CONTENT_READY,
                    body="旧正文",
                ),
                # 日上限用例要第二条成品：同一条成品有未终结任务时被 partial unique
                # 拦住，测不出"跨成品的当日总量"。
                ContentProduct(
                    content_id="c-vid-b",
                    tenant_id="t-vid",
                    product_space_id="ps-vid",
                    final_id="fcw-vid-b",
                    goal="ENGAGEMENT",
                    platform="x_platform",
                    kind="video",
                    status=CONTENT_READY,
                    body="第二条正文",
                ),
            ]
        )
        secret = "sk-video-secret"
        session.add_all(
            [
                AIModel(
                    model_id="m-vid",
                    model_code="agnes-video-2.5-flash",
                    provider="agnes",
                    capability="video",
                    status="active",
                ),
                AIModelKey(
                    model_id="m-vid",
                    ciphertext=crypto.encrypt(secret),
                    fingerprint=crypto.fingerprint(secret),
                    status="active",
                ),
                AISceneRoute(scene=SCENE_VIDEO_GEN, model_id="m-vid"),
            ]
        )
        await session.commit()


async def _route_video_scene_to(factory, model_id: str) -> None:
    """把 VIDEO-GEN 改指到别的模型（用于"注册表没配好"的反例）。"""
    async with factory() as session:
        await session.execute(delete(AISceneRoute).where(AISceneRoute.scene == SCENE_VIDEO_GEN))
        session.add(AISceneRoute(scene=SCENE_VIDEO_GEN, model_id=model_id))
        await session.commit()


class FakeVendor:
    """替身只代**供应商**（驱动本身另有真 httpx 栈单测），并记录调用次数以证"不重投"。"""

    def __init__(self, submit_error: Exception | None = None, poll_result=None):
        self.submit_calls = 0
        self.poll_calls = 0
        self.submit_error = submit_error
        self.poll_result = poll_result or video_drivers.VideoPollResult(
            done=False, succeeded=False, url=None, vendor_status="processing", error=None, raw={}
        )

    async def submit(self, **_kwargs):
        self.submit_calls += 1
        if self.submit_error is not None:
            raise self.submit_error
        return video_drivers.VideoSubmission(video_id="vid-1", task_id="task-1", raw={"video_id": "vid-1"})

    async def poll(self, **_kwargs):
        self.poll_calls += 1
        return self.poll_result


@pytest_asyncio.fixture
async def client(session_factory):
    await _seed_route(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        secret = await issue_staff_token(ac, OPS_ROLES, staff_id="s-vid")
        ac.headers.update(bearer(secret))
        yield ac


@pytest.fixture
def gate_on():
    settings = get_settings()
    before = settings.video_real_enabled
    settings.video_real_enabled = True
    yield settings
    settings.video_real_enabled = before


@pytest.fixture
def vendor(monkeypatch):
    fake = FakeVendor()
    monkeypatch.setattr(video_drivers, "submit_video_task", fake.submit)
    monkeypatch.setattr(video_drivers, "poll_video_task", fake.poll)
    return fake


async def _rows(factory, model, *, where=None):
    async with factory() as session:
        stmt = select(model) if where is None else select(model).where(where)
        return list((await session.scalars(stmt)).all())


async def _video_audits(factory) -> list[str]:
    """只看本族的审计（`issue_staff_token` 自身也写审计，不能按"全部行"断言）。"""
    rows = await _rows(factory, AuditLog, where=AuditLog.action.like("video_task.%"))
    return [row.action for row in rows]


async def _create(client, *, content_id: str = "c-vid", **over):
    body = dict(PARAMS)
    body.update(over)
    return await client.post(_create_path(content_id), json=body)


async def _task_id(client, **over) -> str:
    r = await _create(client, **over)
    assert r.status_code == 201, r.text
    return r.json()["task_id"]


async def _approved(client, task_id: str) -> dict:
    r = await client.post(_task_path(task_id, "/approve"))
    assert r.status_code == 200, r.text
    return r.json()


# ---------- 门控与"登记≠花钱" ----------


async def test_default_is_off_so_nothing_is_written_or_sent(client, session_factory, vendor):
    """V1 现行为：门控默认关 ⇒ 零行、零外部调用（synthetic 链路一字不变）。"""
    assert get_settings().video_real_enabled is False
    r = await _create(client)
    assert r.status_code == 409, r.text
    assert await _rows(session_factory, vs.VideoGenerationTask) == []
    assert vendor.submit_calls == 0 and vendor.poll_calls == 0


async def test_gate_off_blocks_create_approve_and_sync(gate_on, client, session_factory, vendor):
    task_id = await _task_id(client)  # 门控还开着时登记的待审行
    get_settings().video_real_enabled = False
    assert (await _create(client, prompt="while off")).status_code == 409
    assert (await client.post(_task_path(task_id, "/approve"))).status_code == 409
    assert (await client.post(_task_path(task_id, "/sync"))).status_code == 409
    assert vendor.submit_calls == 0 and vendor.poll_calls == 0
    # reject 不花钱也不出网：关掉门控后仍能收掉悬着的待审行，不留孤儿状态
    r = await client.post(_task_path(task_id, "/reject"), json={"reason": "门控已关，先收口"})
    assert r.status_code == 200 and r.json()["status"] == VIDEO_TASK_REJECTED


async def test_create_makes_no_external_call(gate_on, client, session_factory, vendor):
    r = await _create(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == VIDEO_TASK_PENDING
    assert body["url"] is None and body["vendor_video_id"] is None
    assert vendor.submit_calls == 0, "create 就提交＝绕过人工 Gate 直接花钱"
    rows = await _rows(session_factory, vs.VideoGenerationTask)
    assert [row.status for row in rows] == [VIDEO_TASK_PENDING]
    assert rows[0].provider == "agnes" and rows[0].model_code == "agnes-video-2.5-flash"
    assert rows[0].final_id == "fcw-vid" and rows[0].tenant_id == "t-vid"


@pytest.mark.parametrize(
    "over",
    [
        {"mode": "t2v"},  # 官方只有 text/keyframe/reference
        {"seconds": 13},  # 4..12
        {"seconds": 3},
        {"size": "4K"},
        {"aspect_ratio": "5:4"},
        {"prompt": "   "},
    ],
)
async def test_bad_params_are_422(gate_on, client, vendor, over):
    r = await _create(client, **over)
    assert r.status_code == 422, r.text
    assert vendor.submit_calls == 0


async def test_second_open_task_for_the_same_content_is_409(gate_on, client, session_factory, vendor):
    assert (await _create(client)).status_code == 201
    r = await _create(client, prompt="another shot")
    assert r.status_code == 409, r.text
    assert "open video generation task" in r.json()["detail"]
    assert len(await _rows(session_factory, vs.VideoGenerationTask)) == 1


async def test_terminated_task_frees_the_slot(gate_on, client, session_factory, vendor):
    """rejected 不占未终结占位（partial unique 只圈 pending_approval/submitted）。"""
    task_id = await _task_id(client)
    r = await client.post(_task_path(task_id, "/reject"), json={"reason": "文案未定稿"})
    assert r.status_code == 200
    second = await _create(client, prompt="redo after reject")
    assert second.status_code == 201, second.text
    assert len(await _rows(session_factory, vs.VideoGenerationTask)) == 2


async def test_route_not_on_a_video_model_is_409_not_silent_synthetic(client, session_factory, vendor, gate_on):
    """注册表没配好不能悄悄退化成假数据（Q290/Q291 那一族的红线）。"""
    async with session_factory() as session:
        session.add(
            AIModel(
                model_id="m-syn",
                model_code="synthetic-deterministic",
                provider="synthetic",
                capability="chat",
                status="active",
            )
        )
        await session.commit()
    await _route_video_scene_to(session_factory, "m-syn")
    r = await _create(client)
    assert r.status_code == 409, r.text
    assert "capability" in r.json()["detail"]
    assert vendor.submit_calls == 0


# ---------- approve＝花钱那一步 ----------


async def test_approve_submits_once_and_records_the_vendor_ids(gate_on, client, session_factory, vendor):
    task_id = await _task_id(client)
    view = await _approved(client, task_id)
    assert view["status"] == VIDEO_TASK_SUBMITTED
    assert view["vendor_video_id"] == "vid-1" and view["vendor_task_id"] == "task-1"
    assert view["approved_by"] == "s-vid"
    assert vendor.submit_calls == 1
    assert await _video_audits(session_factory) == ["video_task.create", "video_task.approve"]
    # 令牌身份钉死审计（Q351 同纪律）：这些口没有 actor 字段可自报。
    audits = await _rows(session_factory, AuditLog, where=AuditLog.action.like("video_task.%"))
    assert all(a.actor_id == "s-vid" for a in audits)


async def test_submit_failure_is_terminal_and_is_not_retried(gate_on, client, session_factory, vendor):
    vendor.submit_error = video_drivers.VideoDriverError(
        'video submit rejected: 503: {"code":"video_queue_full","message":"video queue is full"}'
    )
    task_id = await _task_id(client)
    r = await client.post(_task_path(task_id, "/approve"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == VIDEO_TASK_FAILED
    assert "video_queue_full" in r.json()["error"]
    assert vendor.submit_calls == 1, "失败后自动重投＝重复扣费（Q354 裁决②）"
    todos = await _rows(session_factory, OpsTodo)
    assert [t.todo_type for t in todos] == [vs.TODO_TYPE_VIDEO_TASK]
    assert todos[0].assignee_role == "operations"
    assert todos[0].status == "open"
    assert todos[0].detail["next_step"]
    actions = await _video_audits(session_factory)
    assert actions == ["video_task.create", "video_task.failed", "video_task.todo_opened"]


async def test_approving_twice_is_409(gate_on, client, vendor):
    task_id = await _task_id(client)
    assert (await _approved(client, task_id))["status"] == VIDEO_TASK_SUBMITTED
    r = await client.post(_task_path(task_id, "/approve"))
    assert r.status_code == 409
    assert vendor.submit_calls == 1


async def test_reject_requires_reason_and_closes_the_row(gate_on, client, vendor):
    task_id = await _task_id(client)
    bad = await client.post(_task_path(task_id, "/reject"), json={"reason": ""})
    assert bad.status_code == 422, bad.text
    r = await client.post(_task_path(task_id, "/reject"), json={"reason": "文案未定稿"})
    assert r.status_code == 200 and r.json()["status"] == VIDEO_TASK_REJECTED
    assert vendor.submit_calls == 0
    assert (await client.post(_task_path(task_id, "/approve"))).status_code == 409


async def test_daily_seconds_cap_blocks_the_next_submission(gate_on, client, vendor, monkeypatch):
    # cap=4、单条 4s：第一条放行（当日已用 0），第二条时已用 4 ⇒ 拦下。第二条用别的成品，
    # 因为同一条成品有未终结任务时先被 partial unique 拦住，测不到跨成品的当日总量。
    monkeypatch.setattr(vs, "knob", lambda key: 4 if key == vs.VIDEO_CAP_KEY else 120)
    first = await _task_id(client)
    assert (await _approved(client, first))["status"] == VIDEO_TASK_SUBMITTED
    second = await _create(client, content_id="c-vid-b", prompt="second shot")
    assert second.status_code == 201, second.text
    r = await client.post(_task_path(second.json()["task_id"], "/approve"))
    assert r.status_code == 409, r.text
    assert "cap reached" in r.json()["detail"]
    assert vendor.submit_calls == 1


# ---------- sync / 超时 ----------


async def test_sync_completes_without_touching_content_body(gate_on, client, session_factory, vendor):
    task_id = await _task_id(client)
    await _approved(client, task_id)
    vendor.poll_result = video_drivers.VideoPollResult(
        done=True, succeeded=True, url="https://cdn.test/v.mp4",
        vendor_status="completed", error=None, raw={},
    )
    r = await client.post(_task_path(task_id, "/sync"))
    assert r.status_code == 200
    assert r.json()["status"] == VIDEO_TASK_COMPLETED
    assert r.json()["url"] == "https://cdn.test/v.mp4"
    contents = await _rows(
        session_factory, ContentProduct, where=ContentProduct.content_id == "c-vid"
    )
    assert contents[0].body == "旧正文", "成片不回写 body（段12 入库口径是下一片）"
    assert "video_task.completed" in await _video_audits(session_factory)


async def test_sync_still_processing_is_not_terminal(gate_on, client, vendor):
    """轮询未到终态就保持 submitted：一次 sync 不改变状态，只累计 polls。"""
    task_id = await _task_id(client)
    await _approved(client, task_id)
    r = await client.post(_task_path(task_id, "/sync"))
    assert r.status_code == 200 and r.json()["status"] == VIDEO_TASK_SUBMITTED
    assert r.json()["polls"] == 1


async def test_poll_error_is_not_terminal(gate_on, client, session_factory, vendor, monkeypatch):
    """单次轮询报错只记 error＋推进 polls；收口交给超时口径，不把网络抖动打成终态。"""

    async def boom(**_kwargs):
        raise video_drivers.VideoDriverError("poll transport failure")

    task_id = await _task_id(client)
    await _approved(client, task_id)
    monkeypatch.setattr(video_drivers, "poll_video_task", boom)
    r = await client.post(_task_path(task_id, "/sync"))
    assert r.status_code == 200 and r.json()["status"] == VIDEO_TASK_SUBMITTED
    assert "transport failure" in r.json()["error"]
    assert await _video_audits(session_factory) == ["video_task.create", "video_task.approve"]


async def test_sweep_times_out_a_stalled_task(gate_on, client, session_factory, vendor):
    task_id = await _task_id(client)
    await _approved(client, task_id)
    settings = get_settings()
    before = settings.video_task_timeout_seconds
    settings.video_task_timeout_seconds = 60.0
    try:
        async with session_factory() as session:
            task = await session.get(vs.VideoGenerationTask, task_id)
            task.approved_at = datetime.now(UTC) - timedelta(hours=1)
            await session.commit()
            # 作业不自行提交（提交/回滚由 sweep runner 统一），测试里就等价地补这一次
            touched = await vs.sweep_video_generation_tasks(session, datetime.now(UTC))
            await session.commit()
    finally:
        settings.video_task_timeout_seconds = before
    assert touched == 1
    assert vendor.poll_calls == 0, "已超时的任务不该再打供应商"
    rows = await _rows(session_factory, vs.VideoGenerationTask)
    assert rows[0].status == VIDEO_TASK_TIMED_OUT
    todos = await _rows(session_factory, OpsTodo)
    assert [t.todo_type for t in todos] == [vs.TODO_TYPE_VIDEO_TASK]


async def test_sweep_respects_the_poll_interval(gate_on, client, session_factory, vendor):
    task_id = await _task_id(client)
    await _approved(client, task_id)
    now = datetime.now(UTC)
    async with session_factory() as session:
        assert await vs.sweep_video_generation_tasks(session, now) == 0
    assert vendor.poll_calls == 0, "approved_at 刚写下＝未到轮询间隔，不该发外部查询"
    async with session_factory() as session:
        task = await session.get(vs.VideoGenerationTask, task_id)
        task.approved_at = now - timedelta(seconds=30)
        await session.commit()
    async with session_factory() as session:
        assert await vs.sweep_video_generation_tasks(session, now) == 0
        await session.commit()
    assert vendor.poll_calls == 1
    rows = await _rows(session_factory, vs.VideoGenerationTask)
    assert rows[0].polls == 1 and rows[0].status == VIDEO_TASK_SUBMITTED
    assert rows[0].last_polled_at is not None


async def test_sweep_is_idle_when_the_gate_is_off(gate_on, client, session_factory, vendor):
    task_id = await _task_id(client)
    await _approved(client, task_id)
    get_settings().video_real_enabled = False
    async with session_factory() as session:
        assert await vs.sweep_video_generation_tasks(session, datetime.now(UTC)) == 0
    assert vendor.poll_calls == 0, "门控关＝作业空转，一条外部查询都不发"


# ---------- 鉴权 ----------


async def test_writes_need_an_operations_token(session_factory, gate_on):
    await _seed_route(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(_create_path(), json=PARAMS)
        assert r.status_code == 401
        async with acting_as(ac, ["product_reviewer"]):
            r2 = await ac.post(_create_path(), json=PARAMS)
            assert r2.status_code == 403


async def test_reads_require_a_management_identity(client):
    no_actor = await client.get(LIST_PATH)
    assert no_actor.status_code == 422, no_actor.text
    wrong_role = await client.get(LIST_PATH, params={"actor_id": "c-1", "roles": "customer"})
    assert wrong_role.status_code == 403
    ok = await client.get(LIST_PATH, params=READ)
    assert ok.status_code == 200 and ok.json() == []


async def test_list_and_get_reads_return_task_views(gate_on, client, vendor):
    task_id = await _task_id(client)
    rows = (await client.get(LIST_PATH, params=READ)).json()
    assert [row["task_id"] for row in rows] == [task_id]
    assert (await client.get(LIST_PATH, params={**READ, "status": VIDEO_TASK_PENDING})).json()
    assert (await client.get(LIST_PATH, params={**READ, "status": VIDEO_TASK_FAILED})).json() == []
    one = await client.get(_task_path(task_id), params=READ)
    assert one.status_code == 200 and one.json()["status"] == VIDEO_TASK_PENDING
    missing = await client.get(_task_path("nope"), params=READ)
    assert missing.status_code == 404
