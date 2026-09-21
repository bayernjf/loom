"""Q87 集成测试：M8 restock_auto worker 消费 requested 信号行。

口径（02 C1.31）：requested 行不 mutate；成功追加 succeeded/llm_auto 子 run 回链
restock_request_id，终态失败追加 failed/llm_auto 子 run，瞬态（预算硬停/上游坏）
不留子 run、下一轮重试；仅认 PWC-BUILDER + source=restock_auto；候选只落
pending_review。create_all 不跑迁移种子，synthetic 模型/路由/Prompt 自插。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.model_registry import drivers
from app.core.model_registry.drivers import GenerationResult
from app.core.model_registry.models import (
    AIModel,
    AISceneRoute,
    SkillPrompt,
    SkillPromptVersion,
)
from app.core.model_registry.seeds import (
    PWC_BUILDER_PROMPT_ID,
    PWC_BUILDER_PROMPT_TEMPLATE,
    PWC_BUILDER_PROMPT_VARIABLES,
    PWC_BUILDER_PROMPT_VERSION,
    SCENE_PWC_BUILDER,
    SYNTHETIC_MODEL_ID,
)
from app.core.models import AuditLog
from app.core.restock.models import RestockClaim, RestockRetryState
from app.core.restock.worker import (
    RestockWorker,
    _backoff_delay_seconds,
    run_restock,
)
from app.core.skill7.models import SkillCandidate, SkillRun
from app.core.skill7.service import PWC_BUILDER, WF04
from app.main import app
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import G2Field

OPS = {"id": "ops-1", "roles": ["operations"]}
PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


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
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async with session_factory() as session:
        session.add_all([
            G2Field(fid="f_a", cat="common", field_name="字段A"),
            G2Field(fid="f_b", cat="selling", field_name="字段B"),
            FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
            AIModel(
                model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
                provider="synthetic", status="active",
            ),
            AISceneRoute(scene=SCENE_PWC_BUILDER, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_PWC_BUILDER, current_version=PWC_BUILDER_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=PWC_BUILDER_PROMPT_ID, skill_id=SCENE_PWC_BUILDER,
                version=PWC_BUILDER_PROMPT_VERSION, template=PWC_BUILDER_PROMPT_TEMPLATE,
                variables={"vars": PWC_BUILDER_PROMPT_VARIABLES},
            ),
        ] + [ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS])
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _dim(i, **kw):
    base = {
        "field_name": f"维度{i}", "role": "product_attribute",
        "source_route": "user_input", "confidence": 0.9, "source_ref": f"ref-{i}",
    }
    base.update(kw)
    return base


async def _make_ps(session_factory, tenant: str = "t1") -> str:
    from app.product.product_intake.models import (
        ProductIntakeApplication,
        ProductSpace,
    )

    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id=tenant, status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id=tenant, intake_id=intake.intake_id, industry_tag="general",
            profile_snapshot={"f_a": "x"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


async def _approved_pool(client, ps_id: str, dim_count: int = 3):
    resp = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools",
        json={"dimensions": [_dim(i, fid="f_a" if i == 1 else "f_b" if i == 2 else None)
                              for i in range(1, dim_count + 1)], "actor": OPS},
    )
    assert resp.status_code == 200, resp.text
    pool_id = resp.json()["pool_id"]
    gate = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text
    return (await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")).json()


async def _approve_atoms(client, ps_id, dims, contents):
    resp = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches",
        json={"items": [
            {"content": contents[i], "dimension_id": dims[i],
             "ai_risk": "low", "evidence": "客服语料"}
            for i in range(len(dims))
        ], "actor": OPS},
    )
    assert resp.status_code == 200, resp.text
    for c in resp.json()["candidates"]:
        ok = await client.post(
            f"/api/atom-candidates/{c['candidate_id']}/approve", json={"actor": REVIEWER}
        )
        assert ok.status_code == 200, ok.text


async def _ps_with_atoms(client, session_factory, contents=("温和洁面", "水润肤感", "清爽质地")):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id, dim_count=3)
    dims = [d["dimension_id"] for d in pool["dimensions"][: len(contents)]]
    await _approve_atoms(client, ps_id, dims, list(contents))
    return ps_id


async def _request_restock(session_factory, ps_id, *, tenant="t1", source="restock_auto",
                           skill_id=PWC_BUILDER) -> str:
    async with session_factory() as session:
        run = SkillRun(
            skill_id=skill_id, wf_id=WF04, tenant_id=tenant, product_space_id=ps_id,
            status="requested", source=source,
            input_payload={"reason": "pool_below_critical", "ready_count": 0, "critical": 5},
            created_by="system",
        )
        session.add(run)
        await session.commit()
        return str(run.run_id)


# ---------- 成功认领 + 反连接幂等 ---------------------------------------------------

async def test_restock_delivers_pending_candidates_and_is_idempotent(client, session_factory):
    ps_id = await _ps_with_atoms(client, session_factory)
    signal_id = await _request_restock(session_factory, ps_id)

    report = await run_restock(session_factory, limit=20)
    assert report["claimed"] == 1 and report["succeeded"] == 1

    async with session_factory() as session:
        signal = await session.get(SkillRun, signal_id)
        # 信号行原样保留（append-only，不 mutate）。
        assert signal.status == "requested" and signal.source == "restock_auto"

        children = list((await session.scalars(
            select(SkillRun).where(
                SkillRun.source == "llm_auto", SkillRun.status == "succeeded"
            )
        )).all())
        assert len(children) == 1
        child = children[0]
        assert child.input_payload["restock_request_id"] == signal_id
        assert child.model_id == SYNTHETIC_MODEL_ID
        cands = list((await session.scalars(
            select(SkillCandidate).where(SkillCandidate.run_id == child.run_id)
        )).all())
        assert cands and all(c.state == "pending_review" for c in cands)
        assert all(c.run_id != signal.run_id for c in cands)

    # 第二轮：反连接认领，不重复消费。
    report_2 = await run_restock(session_factory, limit=20)
    assert report_2["claimed"] == 0


async def test_restock_ignores_non_restock_and_other_skill_signals(client, session_factory):
    ps_id = await _ps_with_atoms(client, session_factory)
    await _request_restock(session_factory, ps_id, source="delivery")
    await _request_restock(session_factory, ps_id, skill_id="CAT-RECOG")
    # 手动 llm-build 的成功行不是 requested 信号（顺带确认不被当信号）。
    report = await run_restock(session_factory, limit=20)
    assert report["claimed"] == 0


# ---------- 终态失败：追加 failed 子 run，不再重试 -----------------------------------

async def test_restock_not_ready_atoms_is_terminal(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id, dim_count=3)
    await _approve_atoms(client, ps_id, [pool["dimensions"][0]["dimension_id"]], ["仅一维有原子"])
    signal_id = await _request_restock(session_factory, ps_id)

    report = await run_restock(session_factory, limit=20)
    assert report["claimed"] == 1 and report["failed"] == 1

    async with session_factory() as session:
        failed = (await session.scalars(
            select(SkillRun).where(
                SkillRun.source == "llm_auto", SkillRun.status == "failed"
            )
        )).one()
        assert failed.input_payload["restock_request_id"] == signal_id
        assert "PwcBuildNotReady" in failed.error
        signal = await session.get(SkillRun, signal_id)
        assert signal.status == "requested"
        audit = (await session.scalars(
            select(AuditLog).where(
                AuditLog.action == "skill7.restock_failed"
            )
        )).one()
        assert audit.detail["terminal"] is True

    assert (await run_restock(session_factory, limit=20))["claimed"] == 0


async def test_restock_pool_not_approved_is_terminal(client, session_factory):
    ps_id = await _make_ps(session_factory)
    await _request_restock(session_factory, ps_id)
    report = await run_restock(session_factory, limit=20)
    assert report["failed"] == 1 and report["claimed"] == 1
    async with session_factory() as session:
        failed = (await session.scalars(
            select(SkillRun).where(SkillRun.status == "failed")
        )).one()
        assert "PoolNotApproved" in failed.error


async def test_restock_disabled_without_fallback_is_terminal(client, session_factory):
    ps_id = await _ps_with_atoms(client, session_factory)
    await _request_restock(session_factory, ps_id)
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-disabled", "provider": "synthetic",
        "actor": PLATFORM_ADMIN,
    })
    disabled_id = r.json()["model_id"]
    r = await client.patch(f"/api/admin/ai-models/{disabled_id}", json={
        "status": "disabled", "actor": PLATFORM_ADMIN,
    })
    assert r.status_code == 200, r.text
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_PWC_BUILDER}", json={
        "model_id": disabled_id, "actor": OPS,
    })
    assert r.status_code == 200

    report = await run_restock(session_factory, limit=20)
    assert report["failed"] == 1
    async with session_factory() as session:
        failed = (await session.scalars(
            select(SkillRun).where(SkillRun.status == "failed")
        )).one()
        assert "ModelUnavailable" in failed.error


async def test_restock_malformed_output_is_terminal(client, session_factory, monkeypatch):
    ps_id = await _ps_with_atoms(client, session_factory)
    await _request_restock(session_factory, ps_id)

    async def _broken(self, **kwargs):
        return GenerationResult(text="not json", input_tokens=3, output_tokens=4)

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _broken)
    report = await run_restock(session_factory, limit=20)
    assert report["failed"] == 1
    async with session_factory() as session:
        failed = (await session.scalars(
            select(SkillRun).where(SkillRun.status == "failed")
        )).one()
        assert "PwcBuildOutputInvalid" in failed.error


# ---------- 瞬态：不留子 run，下一轮重试 ----------------------------------------------

async def test_restock_budget_exhausted_defers_and_retries(client, session_factory):
    ps_id = await _ps_with_atoms(client, session_factory)
    signal_id = await _request_restock(session_factory, ps_id)
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-zero", "provider": "synthetic",
        "daily_budget": 0, "actor": PLATFORM_ADMIN,
    })
    zero_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_PWC_BUILDER}", json={
        "model_id": zero_id, "actor": OPS,
    })
    assert r.status_code == 200

    report = await run_restock(session_factory, limit=20)
    assert report["claimed"] == 1 and report["deferred"] == 1
    async with session_factory() as session:
        children = list((await session.scalars(
            select(SkillRun).where(
                SkillRun.source == "llm_auto"
            )
        )).all())
        assert children == []  # 瞬态不追加子 run
        signal = await session.get(SkillRun, signal_id)
        assert signal.status == "requested"
        audit = (await session.scalars(
            select(AuditLog).where(
                AuditLog.action == "skill7.restock_deferred"
            )
        )).one()
        assert audit.detail["reason"] == "BudgetExhausted"

    # Q90：退避窗口内的定时轮不再认领（游标 attempts=1、下次时间在未来）。
    assert (await run_restock(session_factory, limit=20))["claimed"] == 0
    async with session_factory() as session:
        cursor = await session.get(RestockRetryState, str(signal_id))
        assert cursor is not None
        assert cursor.attempts == 1
        assert cursor.last_reason == "BudgetExhausted"
        assert cursor.next_attempt_at.replace(tzinfo=UTC) > datetime.now(UTC)

    # 手工 /run 同口径（honor_backoff=False）绕过窗口，仍瞬态则 attempts 累加到 2。
    report = await run_restock(session_factory, limit=20, honor_backoff=False)
    assert report["claimed"] == 1 and report["deferred"] == 1
    async with session_factory() as session:
        cursor = await session.get(RestockRetryState, str(signal_id))
        assert cursor.attempts == 2


# ---------- 管理端点 / worker 生命周期 ------------------------------------------------

async def test_admin_restock_run_rbac_and_triggers(client, session_factory):
    r = await client.post("/api/admin/restock/run", json={"actor": CUSTOMER})
    assert r.status_code == 403
    r = await client.post("/api/admin/restock/run", json={"actor": OPS})
    assert r.status_code == 403

    ps_id = await _ps_with_atoms(client, session_factory)
    await _request_restock(session_factory, ps_id)
    r = await client.post("/api/admin/restock/run", json={"actor": PLATFORM_ADMIN})
    assert r.status_code == 200, r.text
    assert r.json()["claimed"] == 1 and r.json()["succeeded"] == 1


async def test_restock_worker_lifecycle_start_stop(session_factory):
    worker = RestockWorker(session_factory, interval_seconds=0.02, batch_size=5)
    await worker.start()
    assert worker.running
    await worker.stop()
    assert not worker.running


# ---------- Q90 瞬态退避游标 -----------------------------------------------------------

def test_backoff_delay_sequence_and_cap():
    # 默认 base=60s：60,120,240,480,960，第 6 次 1920 被封顶到 1800。
    assert [_backoff_delay_seconds(n) for n in range(1, 7)] == [
        60.0, 120.0, 240.0, 480.0, 960.0, 1800.0
    ]
    assert _backoff_delay_seconds(20) == 1800.0


async def test_backoff_window_expires_then_signal_claimed_again(
    client, session_factory
):
    ps_id = await _ps_with_atoms(client, session_factory)
    signal_id = await _request_restock(session_factory, ps_id)
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-zero", "provider": "synthetic",
        "daily_budget": 0, "actor": PLATFORM_ADMIN,
    })
    zero_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_PWC_BUILDER}", json={
        "model_id": zero_id, "actor": OPS,
    })
    assert r.status_code == 200

    report = await run_restock(session_factory, limit=20)
    assert report["deferred"] == 1
    # 窗口内定时轮跳过。
    assert (await run_restock(session_factory, limit=20))["claimed"] == 0

    # 把下次可重试时间拨到过去（模拟退避窗口已过），定时轮重新认领、attempts 累加。
    async with session_factory() as session:
        cursor = await session.get(RestockRetryState, str(signal_id))
        cursor.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    report = await run_restock(session_factory, limit=20)
    assert report["claimed"] == 1 and report["deferred"] == 1
    async with session_factory() as session:
        cursor = await session.get(RestockRetryState, str(signal_id))
        assert cursor.attempts == 2


async def test_budget_exhausted_never_escalates(client, session_factory):
    ps_id = await _ps_with_atoms(client, session_factory)
    signal_id = await _request_restock(session_factory, ps_id)
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-zero", "provider": "synthetic",
        "daily_budget": 0, "actor": PLATFORM_ADMIN,
    })
    zero_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_PWC_BUILDER}", json={
        "model_id": zero_id, "actor": OPS,
    })
    assert r.status_code == 200

    # 超过上限（10）连续手动强试，仍只 defer（UTC 次日预算自愈，绝不转终态）。
    for _ in range(11):
        report = await run_restock(
            session_factory, limit=20, honor_backoff=False
        )
        assert report["deferred"] == 1
    async with session_factory() as session:
        cursor = await session.get(RestockRetryState, str(signal_id))
        assert cursor.attempts == 11
        assert cursor.last_reason == "BudgetExhausted"
        assert (await session.scalars(
            select(SkillRun).where(SkillRun.source == "llm_auto")
        )).all() == []
        assert (await session.scalars(
            select(AuditLog).where(AuditLog.action == "skill7.restock_failed")
        )).all() == []


async def test_upstream_error_escalates_after_max_attempts(
    client, session_factory, monkeypatch
):
    ps_id = await _ps_with_atoms(client, session_factory)
    signal_id = await _request_restock(session_factory, ps_id)

    async def _upstream_down(self, **kwargs):
        raise drivers.DriverError("upstream 502")

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _upstream_down)

    # 前 9 次（手动绕窗口）defer，第 10 次转终态。
    for attempt in range(1, 10):
        report = await run_restock(
            session_factory, limit=20, honor_backoff=False
        )
        assert report["deferred"] == 1
        async with session_factory() as session:
            cursor = await session.get(RestockRetryState, str(signal_id))
            assert cursor.attempts == attempt
    report = await run_restock(session_factory, limit=20, honor_backoff=False)
    assert report["failed"] == 1
    assert report["runs"][str(signal_id)]["attempts"] == 10

    async with session_factory() as session:
        # 终态：failed/llm_auto 子 run + restock_failed(terminal, attempts=10)，游标删除。
        assert await session.get(RestockRetryState, str(signal_id)) is None
        failed = (await session.scalars(
            select(SkillRun).where(SkillRun.status == "failed")
        )).one()
        assert failed.source == "llm_auto"
        assert "GenerationUpstreamError" in failed.error
        audit = (await session.scalars(
            select(AuditLog).where(
                AuditLog.action == "skill7.restock_failed"
            )
        )).one()
        assert audit.detail["terminal"] is True
        assert audit.detail["attempts"] == 10

    # 终态后信号被反连接排除，不再认领。
    assert (await run_restock(session_factory, limit=20))["claimed"] == 0


async def test_success_clears_backoff_cursor(client, session_factory):
    ps_id = await _ps_with_atoms(client, session_factory)
    signal_id = await _request_restock(session_factory, ps_id)
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-zero", "provider": "synthetic",
        "daily_budget": 0, "actor": PLATFORM_ADMIN,
    })
    zero_id = r.json()["model_id"]
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_PWC_BUILDER}", json={
        "model_id": zero_id, "actor": OPS,
    })
    assert r.status_code == 200
    assert (await run_restock(session_factory, limit=20))["deferred"] == 1

    # 预算恢复：路由切回 synthetic 正常模型，手动强试成功后游标删除。
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_PWC_BUILDER}", json={
        "model_id": SYNTHETIC_MODEL_ID, "actor": OPS,
    })
    assert r.status_code == 200
    report = await run_restock(session_factory, limit=20, honor_backoff=False)
    assert report["succeeded"] == 1
    async with session_factory() as session:
        assert await session.get(RestockRetryState, str(signal_id)) is None


async def test_terminal_failure_clears_existing_cursor(
    client, session_factory, monkeypatch
):
    ps_id = await _ps_with_atoms(client, session_factory)
    signal_id = await _request_restock(session_factory, ps_id)
    async with session_factory() as session:
        session.add(RestockRetryState(
            request_id=str(signal_id),
            attempts=3,
            next_attempt_at=datetime.now(UTC) + timedelta(hours=1),
            last_reason="BudgetExhausted",
        ))
        await session.commit()

    async def _broken(self, **kwargs):
        return GenerationResult(text="not json", input_tokens=3, output_tokens=4)

    monkeypatch.setattr(drivers.SyntheticDriver, "generate", _broken)
    # 终态错误即使在退避窗口内也由手动触发撞出；定时轮因窗口跳过。
    report = await run_restock(session_factory, limit=20, honor_backoff=False)
    assert report["failed"] == 1
    async with session_factory() as session:
        assert await session.get(RestockRetryState, str(signal_id)) is None


# ---------- Q143 PG 行级 fencing（fence 认领 + 提交前门） -----------------------------


async def test_restock_with_fence_succeeds_and_records_claim(
    client, session_factory
):
    ps_id = await _ps_with_atoms(client, session_factory)
    signal_id = await _request_restock(session_factory, ps_id)
    report = await run_restock(
        session_factory, limit=20, fence=1, owner="owner-a"
    )
    assert report["succeeded"] == 1
    assert report["skipped_lost"] == 0
    async with session_factory() as session:
        claim = await session.get(RestockClaim, str(signal_id))
        assert claim is not None and claim.fence == 1
        assert claim.claimed_by == "owner-a"


async def test_restock_skips_when_claim_held_by_newer_fence(
    client, session_factory
):
    ps_id = await _ps_with_atoms(client, session_factory)
    signal_id = await _request_restock(session_factory, ps_id)
    # 新 leader（fence=2）已认领：旧 leader fence=1 在花钱前直接放弃，不调模型。
    async with session_factory() as session:
        session.add(
            RestockClaim(
                request_id=str(signal_id), fence=2, claimed_by="owner-b"
            )
        )
        await session.commit()
    report = await run_restock(
        session_factory, limit=20, fence=1, owner="owner-a"
    )
    assert report["claimed"] == 1
    assert report["skipped_lost"] == 1
    assert report["succeeded"] == 0
    async with session_factory() as session:
        children = list(
            (
                await session.scalars(
                    select(SkillRun).where(SkillRun.source == "llm_auto")
                )
            ).all()
        )
        assert children == []  # 未花钱、未产子 run


async def test_fence_gate_rejects_result_when_lock_lost_during_spend(
    client, session_factory, monkeypatch
):
    from app.core.restock import worker as restock_worker

    ps_id = await _ps_with_atoms(client, session_factory)
    signal_id = await _request_restock(session_factory, ps_id)

    # 模型已成功返回、成功结果在业务事务内 flush；此时锁在一次调用期间易主，
    # 提交前门条件更新命中 0 行。门的真实 SQL 条件（fence 被更大值覆盖即 0 行）
    # 由 test_restock_fencing.py 覆盖，这里把门关死以确定性验证 worker 的回滚路径
    # （sqlite 内存库单连接无法在业务事务打开时并发提交另一事务，故不模拟跨连接）。
    async def _gate_closed(session, request_id, fence):
        return False

    monkeypatch.setattr(restock_worker, "fence_current", _gate_closed)
    report = await run_restock(
        session_factory, limit=20, fence=1, owner="owner-a"
    )
    assert report["skipped_lost"] == 1
    assert report["succeeded"] == 0
    async with session_factory() as session:
        # 旧 leader 的成功结果随回滚不落库：无 llm_auto 子 run、无候选。
        assert (
            list(
                (
                    await session.scalars(
                        select(SkillRun).where(SkillRun.source == "llm_auto")
                    )
                ).all()
            )
            == []
        )
        assert list((await session.scalars(select(SkillCandidate))).all()) == []
        # 花钱前的认领行仍在（fence=1，由本 leader 短事务提交，不受回滚影响）。
        claim = await session.get(RestockClaim, str(signal_id))
        assert claim is not None and claim.fence == 1
