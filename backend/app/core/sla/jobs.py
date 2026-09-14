"""SLA sweep 作业登记（Q49/Q18/Q24/Q51）。

每个作业签名 (session, now) -> int（影响行数），不自行提交，提交/回滚由 runner 统一，
保证单个作业失败不污染其他作业。跨域依赖（decision 包）惰性导入，避免 core 反向依赖。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.compliance_wordlist.models import ComplianceWordlistEntry
from app.core.sla.engine import escalate_due_todos
from app.product.atom.service import sweep_evidence_timeouts
from app.product.condition.service import sweep_cooldowns


async def job_todo_escalation(session: AsyncSession, now: datetime) -> int:
    return len(await escalate_due_todos(session, now))


async def job_atom_evidence_timeout(session: AsyncSession, now: datetime) -> int:
    return await sweep_evidence_timeouts(session, now)


async def job_pwc_cooldown_release(session: AsyncSession, now: datetime) -> int:
    return await sweep_cooldowns(session, now)


async def job_wordlist_activation(session: AsyncSession, now: datetime) -> int:
    """Q51 未来生效词条：到达生效时点 → 标记激活并补跑生效即扫。"""
    from app.decision.compliance_center.service import rescan_for_entry

    pending = (
        await session.scalars(
            select(ComplianceWordlistEntry).where(
                ComplianceWordlistEntry.status == "active",
                ComplianceWordlistEntry.activated_at.is_(None),
                ComplianceWordlistEntry.effective_from.is_not(None),
                ComplianceWordlistEntry.effective_from <= now,
            )
        )
    ).all()
    for entry in pending:
        entry.activated_at = now
        await rescan_for_entry(session, entry)
    return len(pending)


# 登记顺序即执行顺序。
JOBS = [
    ("todo_escalation", job_todo_escalation),
    ("atom_evidence_timeout", job_atom_evidence_timeout),
    ("pwc_cooldown_release", job_pwc_cooldown_release),
    ("wordlist_activation", job_wordlist_activation),
]
