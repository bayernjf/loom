"""C1 自动识别 worker：消费停留在 ``ai_recognizing`` 的 intake。

设计口径：

1. 只处理 ``ai_recognizing`` 且没有任何 c1 候选的 intake；已有候选（含人工
   驳回后的 archived）时跳过，既避免重复花钱，也不绕过人工 Gate。
2. 调用既有 ``extraction.invoke_c1_recognition``，产出仍落 ``pending_review``；
   本 worker 只负责“触发识别”，不确认候选、不写 C1Record。
3. 单条处理、单条事务；失败只记录并跳过，下一轮可重试。
4. 默认关闭，部署/local 显式开 ``LOOM_C1_WORKER_ENABLED=true``，因为真模型
   会自动花 token；测试/本地 synthetic route 可安全使用。
"""

import asyncio
import contextlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.actor import Actor
from app.core.model_registry import extraction
from app.core.rbac import OPERATIONS
from app.core.skill7.models import SkillCandidate
from app.core.staff_auth.context import reset_current_staff, set_current_staff
from app.product.modeling.models import C1Record
from app.product.product_intake import statemachine as sm
from app.product.product_intake.models import ProductIntakeApplication

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = Actor(id="system:c1-recognition-worker", roles=[OPERATIONS])


async def _has_c1_candidate(session: AsyncSession, intake_id: str) -> bool:
    """任一状态的 c1 候选都算已识别过；人工驳回后不自动重跑。"""
    return bool(
        await session.scalar(
            select(SkillCandidate.candidate_id)
            .where(
                SkillCandidate.intake_id == intake_id,
                SkillCandidate.target_type == "c1_recognition",
            )
            .limit(1)
        )
    )


async def _has_c1_record(session: AsyncSession, intake_id: str) -> bool:
    return bool(
        await session.scalar(
            select(C1Record.record_id)
            .where(C1Record.intake_id == intake_id)
            .limit(1)
        )
    )


async def run_c1_once(
    session_factory: async_sessionmaker[AsyncSession], *, limit: int = 10
) -> dict:
    """跑一轮 C1 识别；返回 checked/processed/skipped/errors/runs。"""
    async with session_factory() as session:
        intake_ids = list(
            (
                await session.scalars(
                    select(ProductIntakeApplication.intake_id)
                    .where(ProductIntakeApplication.status == sm.AI_RECOGNIZING)
                    .order_by(ProductIntakeApplication.created_at)
                    .limit(limit)
                )
            ).all()
        )

    report: dict = {
        "checked": len(intake_ids),
        "processed": 0,
        "skipped": 0,
        "errors": [],
        "runs": {},
    }
    for intake_id in intake_ids:
        async with session_factory() as session:
            intake = await session.get(ProductIntakeApplication, intake_id)
            if intake is None or intake.status != sm.AI_RECOGNIZING:
                report["skipped"] += 1
                continue
            if await _has_c1_candidate(session, intake_id) or await _has_c1_record(
                session, intake_id
            ):
                report["skipped"] += 1
                continue

            # 内部 worker 没有 HTTP 请求上下文；放入系统身份供 RBAC/审计使用。
            set_current_staff(SYSTEM_ACTOR)
            try:
                run, candidates = await extraction.invoke_c1_recognition(
                    session, intake_id, SYSTEM_ACTOR
                )
                await session.commit()
            except Exception as exc:  # noqa: BLE001 - worker 单条失败不拖垮整轮
                await session.rollback()
                logger.warning(
                    "c1 recognition failed for intake %s: %s: %s",
                    intake_id,
                    exc.__class__.__name__,
                    exc,
                )
                report["errors"].append(
                    {"intake_id": intake_id, "error": f"{exc.__class__.__name__}: {exc}"}
                )
                continue
            finally:
                reset_current_staff()

            report["processed"] += 1
            report["runs"][intake_id] = {
                "run_id": run.run_id,
                "candidate_ids": [c.candidate_id for c in candidates],
            }
    return report


class C1RecognitionWorker:
    """进程内定时 C1 识别 worker，形态与 RestockWorker 同构。"""

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
        self._task = asyncio.create_task(self._loop(), name="loom-c1-worker")

    async def _tick(self) -> None:
        report = await run_c1_once(self._factory, limit=self._batch_size)
        if report["processed"] or report["errors"]:
            logger.info("c1 recognition sweep: %s", report)

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
                logger.exception("c1 recognition sweep failed")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
