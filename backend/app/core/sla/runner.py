"""统一 sweep runner：每作业独立会话，异常隔离不阻断其余（Q49 引擎调度面）。"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.locking import LockLost
from app.core.sla.jobs import JOBS


async def run_jobs(
    session_factory: Callable,
    now: datetime | None = None,
    only: list[str] | None = None,
    checkpoint: Callable[[], None] | None = None,
    commit_guard: Callable[[AsyncSession], Awaitable[bool]] | None = None,
) -> dict[str, dict]:
    """顺序执行登记作业。

    返回 {job_name: {"changed": n}} 或 {"error": "..."}；
    每个作业一个会话，失败回滚不影响后续作业。

    Q139：``checkpoint``（持锁方的 ``lease.raise_if_lost``）在每个作业开始前调用，
    锁中途易主时抛 LockLost 协作中止，后续作业本轮不再执行（手工 /run 不传则恒跑完）。

    Q151：``commit_guard``（持锁方的 PG 行级 fence 条件更新）在作业跑完、提交前
    调用，返回 False 表示锁在该作业执行期间易主、认领已被更大 fence 抢占：回滚
    该作业并抛 LockLost 中止本轮（旧 leader 的迟到写入不落库）。
    """
    now = now or datetime.now(UTC)
    selected = [(name, fn) for name, fn in JOBS if only is None or name in only]
    report: dict[str, dict] = {}
    for name, fn in selected:
        if checkpoint is not None:
            checkpoint()
        async with session_factory() as session:
            try:
                changed = await fn(session, now)
            except Exception as exc:  # noqa: BLE001 - 调度隔离：记录错误继续后续作业
                await session.rollback()
                report[name] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            if commit_guard is not None and not await commit_guard(session):
                await session.rollback()
                report[name] = {"error": "LockLost: fence overtaken before commit"}
                raise LockLost(
                    f"sweep job {name} rejected by fence gate before commit"
                )
            await session.commit()
            report[name] = {"changed": changed}
    return report
