"""Q87 M8 restock_auto worker：消费 Q71/Q76-4 落下的 requested 信号行。

口径（02 C1.31 四接缝，均为负责人拍板推荐项）：

1. 形态：V1 进程内 asyncio loop（RestockWorker），与 SLA SweepScheduler 同构；
   默认关闭（LOOM_RESTOCK_WORKER_ENABLED=true 显式开启，因为会自动花真 token）；
   Redis Streams/多副本单实例锁挂账 V2（docs/07 §7.5 队列选型 V1 裁决为进程内轮询）。
2. 认领纯追加：requested 信号行绝不 mutate；成功追加 succeeded/llm_auto 子 run
   （input.restock_request_id 回链），终态失败追加 failed/llm_auto 子 run；
   认领查询 = requested 行反连接已有子 run。瞬态失败不留子 run，下一轮重试。
3. 范围：仅 PWC-BUILDER（当前唯一 requested 写者）；只产 pending_review 候选，
   人工 Gate 一字不改；不自动串 ATOM-EXPAND。
4. 失败分类：配置/状态类（PS 消失、池未批、素材不足、结构脏输出、缺路由/Prompt/Key、
   停用无 fallback）为终态；日预算硬停、上游传输错误为瞬态。
"""

import asyncio
import contextlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.model_registry import gateway, pwc_build
from app.core.model_registry.pwc_build import SYSTEM_ACTOR
from app.core.skill7.models import SkillRun
from app.core.skill7.service import PWC_BUILDER, WF04

logger = logging.getLogger(__name__)

# 终态：补一条 failed 子 run 后不再重试（重试只会重复烧 token 或永不成立）。
TERMINAL_EXCEPTIONS = (
    pwc_build.ProductSpaceNotFound,
    pwc_build.PoolNotApproved,
    pwc_build.PwcBuildNotReady,
    pwc_build.PwcBuildOutputInvalid,
    gateway.ModelConfigError,
    gateway.ModelUnavailable,  # BudgetExhausted 是其子类，必须在前面单独 except
)
# 瞬态：requested 行保留、记审计，下一轮自然重试。
TRANSIENT_EXCEPTIONS = (
    gateway.BudgetExhausted,
    gateway.GenerationUpstreamError,
)


async def _claim_pending(session: AsyncSession, limit: int) -> list[SkillRun]:
    rows = list(
        (
            await session.scalars(
                select(SkillRun)
                .where(
                    SkillRun.skill_id == PWC_BUILDER,
                    SkillRun.status == "requested",
                    SkillRun.source == "restock_auto",
                )
                .order_by(SkillRun.created_at.asc())
            )
        ).all()
    )
    payloads = (
        await session.scalars(
            select(SkillRun.input_payload).where(SkillRun.source == "llm_auto")
        )
    ).all()
    consumed = {
        str(payload.get("restock_request_id"))
        for payload in payloads
        if isinstance(payload, dict) and payload.get("restock_request_id")
    }
    return [row for row in rows if str(row.run_id) not in consumed][:limit]


async def _record_terminal_failure(
    session: AsyncSession, requested: SkillRun, exc: Exception
) -> None:
    session.add(
        SkillRun(
            skill_id=PWC_BUILDER,
            wf_id=WF04,
            tenant_id=requested.tenant_id,
            product_space_id=requested.product_space_id,
            status="failed",
            source="llm_auto",
            input_payload={"restock_request_id": str(requested.run_id)},
            error=f"{type(exc).__name__}: {exc}",
            created_by=SYSTEM_ACTOR.id,
        )
    )
    await append_audit(
        session,
        tenant_id=requested.tenant_id,
        actor_id=SYSTEM_ACTOR.id,
        actor_roles=SYSTEM_ACTOR.roles,
        action="skill7.restock_failed",
        entity_type="skill_run",
        entity_id=str(requested.run_id),
        detail={"reason": type(exc).__name__, "terminal": True},
    )


async def _process_one(session_factory, requested: SkillRun) -> dict:
    request_id = str(requested.run_id)
    async with session_factory() as session:
        try:
            _run, candidates = await pwc_build.invoke_pwc_build_for_restock(
                session, requested.product_space_id, restock_request_id=request_id
            )
            await append_audit(
                session,
                tenant_id=requested.tenant_id,
                actor_id=SYSTEM_ACTOR.id,
                actor_roles=SYSTEM_ACTOR.roles,
                action="skill7.restock_delivered",
                entity_type="skill_run",
                entity_id=request_id,
                detail={"candidates": len(candidates)},
            )
            await session.commit()
            return {"status": "succeeded", "candidates": len(candidates)}
        except TRANSIENT_EXCEPTIONS as exc:
            await session.rollback()
            async with session_factory() as audit_session:
                await append_audit(
                    audit_session,
                    tenant_id=requested.tenant_id,
                    actor_id=SYSTEM_ACTOR.id,
                    actor_roles=SYSTEM_ACTOR.roles,
                    action="skill7.restock_deferred",
                    entity_type="skill_run",
                    entity_id=request_id,
                    detail={"reason": type(exc).__name__, "terminal": False},
                )
                await audit_session.commit()
            logger.warning("restock %s deferred: %s", request_id, exc)
            return {"status": "deferred", "reason": type(exc).__name__}
        except TERMINAL_EXCEPTIONS as exc:
            # BudgetExhausted 已在上面的瞬态分支截走；落到这里的 ModelUnavailable
            # 只剩停用无 fallback。
            await session.rollback()
            async with session_factory() as fail_session:
                await _record_terminal_failure(fail_session, requested, exc)
                await fail_session.commit()
            logger.warning("restock %s terminally failed: %s", request_id, exc)
            return {"status": "failed", "reason": type(exc).__name__}
        except Exception:  # 未预期异常不拖垮整轮，信号行留待排查
            await session.rollback()
            logger.exception("restock %s errored unexpectedly", request_id)
            return {"status": "error", "reason": "unexpected"}


async def run_restock(session_factory, *, limit: int = 20) -> dict:
    """跑一轮补货。每条信号行独立会话/提交，互不污染（同 SLA runner 口径）。"""
    async with session_factory() as session:
        pending = await _claim_pending(session, limit)
    report: dict[str, dict] = {}
    for requested in pending:
        report[str(requested.run_id)] = await _process_one(session_factory, requested)
    return {
        "claimed": len(pending),
        "succeeded": sum(1 for r in report.values() if r["status"] == "succeeded"),
        "failed": sum(1 for r in report.values() if r["status"] == "failed"),
        "deferred": sum(1 for r in report.values() if r["status"] == "deferred"),
        "runs": report,
    }


class RestockWorker:
    """进程内定时补货 worker，形态与 SweepScheduler 同构（V1 单进程）。"""

    def __init__(self, session_factory, interval_seconds: float, batch_size: int):
        self._factory = session_factory
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="loom-restock-worker")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            try:
                report = await run_restock(self._factory, limit=self._batch_size)
                if report["claimed"]:
                    logger.info("restock sweep: %s", report)
            except Exception:
                logger.exception("restock sweep failed")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
