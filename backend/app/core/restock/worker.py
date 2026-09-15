"""Q87 M8 restock_auto worker：消费 Q71/Q76-4 落下的 requested 信号行。

口径（02 C1.31 四接缝 + C1.33 Q89 锁 + C1.34 Q90 退避，均为负责人拍板推荐项）：

1. 形态：V1 进程内 asyncio loop（RestockWorker），与 SLA SweepScheduler 同构；
   默认关闭（LOOM_RESTOCK_WORKER_ENABLED=true 显式开启，因为会自动花真 token）；
   多副本下单实例执行由 Q89 Redis leader 锁保证（env 门控，默认关）；
   Redis Streams/每信号行细粒度认领挂账 V2（docs/07 §7.5）。
2. 认领纯追加：requested 信号行绝不 mutate；成功追加 succeeded/llm_auto 子 run
   （input.restock_request_id 回链），终态失败追加 failed/llm_auto 子 run；
   认领查询 = requested 行反连接已有子 run。
3. 范围：仅 PWC-BUILDER（当前唯一 requested 写者）；只产 pending_review 候选，
   人工 Gate 一字不改；不自动串 ATOM-EXPAND。
4. 失败分类：配置/状态类（PS 消失、池未批、素材不足、结构脏输出、缺路由/Prompt/Key、
   停用无 fallback）为终态；日预算硬停、上游传输错误为瞬态。
5. Q90 瞬态退避：重试次数/next_attempt_at 落 restock_retry_state 游标表
   （requested 行不 mutate），指数退避 base×2^(attempts-1) 封顶；上游传输错
   累计 max_attempts 次转终态 failed（人工介入），日预算硬停（UTC 次日恢复）
   永不转终态；手工 /run（honor_backoff=False）绕过退避窗口。
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.db import settings
from app.core.locking import (
    RESTOCK_LOCK,
    LockBackendError,
    LockUnavailable,
    leader_lock,
)
from app.core.model_registry import gateway, pwc_build
from app.core.model_registry.pwc_build import SYSTEM_ACTOR
from app.core.restock.models import RestockRetryState
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


def _backoff_delay_seconds(attempts: int) -> float:
    """Q90 指数退避：base×2^(attempts-1)，封顶 max（默认 60s→…→1800s）。"""
    return min(
        settings.restock_backoff_base_seconds * 2 ** (attempts - 1),
        settings.restock_backoff_max_seconds,
    )


def _as_utc(value: datetime) -> datetime:
    # SQLite 回读不带 tzinfo，统一按 UTC 解释后再与 aware 的 now 比较。
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _claim_pending(
    session: AsyncSession, limit: int, *, now: datetime, honor_backoff: bool
) -> list[SkillRun]:
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
    pending = [row for row in rows if str(row.run_id) not in consumed]
    if honor_backoff and pending:
        cursors = {
            cursor.request_id: cursor
            for cursor in (
                await session.scalars(
                    select(RestockRetryState).where(
                        RestockRetryState.request_id.in_(
                            [str(row.run_id) for row in pending]
                        )
                    )
                )
            ).all()
        }
        pending = [
            row
            for row in pending
            if (cursor := cursors.get(str(row.run_id))) is None
            or _as_utc(cursor.next_attempt_at) <= now
        ]
    return pending[:limit]


async def _record_terminal_failure(
    session: AsyncSession,
    requested: SkillRun,
    exc: Exception,
    *,
    attempts: int | None = None,
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
    detail: dict = {"reason": type(exc).__name__, "terminal": True}
    if attempts is not None:
        detail["attempts"] = attempts
    await append_audit(
        session,
        tenant_id=requested.tenant_id,
        actor_id=SYSTEM_ACTOR.id,
        actor_roles=SYSTEM_ACTOR.roles,
        action="skill7.restock_failed",
        entity_type="skill_run",
        entity_id=str(requested.run_id),
        detail=detail,
    )


async def _process_one(session_factory, requested: SkillRun) -> dict:
    request_id = str(requested.run_id)
    async with session_factory() as session:
        try:
            _run, candidates = await pwc_build.invoke_pwc_build_for_restock(
                session, requested.product_space_id, restock_request_id=request_id
            )
            # 成功即清退避游标（游标是执行态，信号成功后不再需要）。
            cursor = await session.get(RestockRetryState, request_id)
            if cursor is not None:
                await session.delete(cursor)
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
            reason = type(exc).__name__
            async with session_factory() as retry_session:
                cursor = await retry_session.get(RestockRetryState, request_id)
                attempts = (cursor.attempts if cursor else 0) + 1
                next_at = datetime.now(UTC) + timedelta(
                    seconds=_backoff_delay_seconds(attempts)
                )
                if cursor is None:
                    cursor = RestockRetryState(request_id=request_id)
                    retry_session.add(cursor)
                cursor.attempts = attempts
                cursor.next_attempt_at = next_at
                cursor.last_reason = reason
                # 仅上游传输错累计到上限转终态；BudgetExhausted 靠 UTC 日界
                # 预算自愈，永不转终态（转了反而错过补货）。
                escalated = (
                    isinstance(exc, gateway.GenerationUpstreamError)
                    and attempts >= settings.restock_backoff_max_attempts
                )
                if escalated:
                    await retry_session.delete(cursor)
                    await _record_terminal_failure(
                        retry_session, requested, exc, attempts=attempts
                    )
                else:
                    await append_audit(
                        retry_session,
                        tenant_id=requested.tenant_id,
                        actor_id=SYSTEM_ACTOR.id,
                        actor_roles=SYSTEM_ACTOR.roles,
                        action="skill7.restock_deferred",
                        entity_type="skill_run",
                        entity_id=request_id,
                        detail={
                            "reason": reason,
                            "terminal": False,
                            "attempts": attempts,
                        },
                    )
                await retry_session.commit()
            if escalated:
                logger.warning(
                    "restock %s escalated to terminal after %s upstream failures",
                    request_id,
                    attempts,
                )
                return {"status": "failed", "reason": reason, "attempts": attempts}
            logger.warning(
                "restock %s deferred (attempt %s, next at %s): %s",
                request_id,
                attempts,
                next_at.isoformat(),
                exc,
            )
            return {"status": "deferred", "reason": reason, "attempts": attempts}
        except TERMINAL_EXCEPTIONS as exc:
            # BudgetExhausted 已在上面的瞬态分支截走；落到这里的 ModelUnavailable
            # 只剩停用无 fallback。
            await session.rollback()
            async with session_factory() as fail_session:
                cursor = await fail_session.get(RestockRetryState, request_id)
                if cursor is not None:
                    await fail_session.delete(cursor)
                await _record_terminal_failure(fail_session, requested, exc)
                await fail_session.commit()
            logger.warning("restock %s terminally failed: %s", request_id, exc)
            return {"status": "failed", "reason": type(exc).__name__}
        except Exception:  # 未预期异常不拖垮整轮，信号行留待排查
            await session.rollback()
            logger.exception("restock %s errored unexpectedly", request_id)
            return {"status": "error", "reason": "unexpected"}


async def run_restock(
    session_factory, *, limit: int = 20, honor_backoff: bool = True
) -> dict:
    """跑一轮补货。每条信号行独立会话/提交，互不污染（同 SLA runner 口径）。

    honor_backoff=False 用于手工 /run：绕过退避窗口立即尝试；尝试仍为瞬态时
    照常累加 attempts 并重排下次窗口（Q90 接缝④）。
    """
    now = datetime.now(UTC)
    async with session_factory() as session:
        pending = await _claim_pending(
            session, limit, now=now, honor_backoff=honor_backoff
        )
    report: dict[str, dict] = {}
    for requested in pending:
        report[str(requested.run_id)] = await _process_one(session_factory, requested)
    return {
        "claimed": len(pending),
        "honor_backoff": honor_backoff,
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

    async def _tick(self) -> None:
        """跑一轮补货；多副本下非持锁副本/Redis 故障均跳过（Q89，防双花）。"""
        try:
            async with leader_lock(RESTOCK_LOCK):
                report = await run_restock(self._factory, limit=self._batch_size)
        except LockUnavailable:
            logger.info("restock tick skipped: leader lock held by another replica")
            return
        except LockBackendError:
            logger.exception("restock tick skipped: lock backend unavailable")
            return
        if report["claimed"]:
            logger.info("restock sweep: %s", report)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            try:
                await self._tick()
            except Exception:
                logger.exception("restock sweep failed")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
