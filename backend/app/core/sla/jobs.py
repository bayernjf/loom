"""SLA sweep 作业登记（Q49/Q18/Q24/Q51；Q187 第五作业 discard_purge）。

每个作业签名 (session, now) -> int（影响行数），不自行提交，提交/回滚由 runner 统一，
保证单个作业失败不污染其他作业。跨域依赖（decision/content 包）惰性导入，避免 core
反向依赖。
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


async def job_discard_purge(session: AsyncSession, now: datetime) -> int:
    """Q187/C4：过保留期且无下游引用的段12 discarded 成品物理清理。

    破坏性动作，故 env 门控 ``LOOM_DISCARD_PURGE_ENABLED`` 默认关（同 Q87/Q137/
    Q161 先例）：关时本作业空转返回 0，V1 既有 sweep 行为一字不变。开启后保留
    窗口与批量上限分别取配置中心 content.discard_retention_days 与 env
    LOOM_DISCARD_PURGE_BATCH；有 effect_records/effect_claims/import_jobs 引用的
    行留档不删（见 service.purge_expired_discarded）。
    """
    from app.content.service import purge_expired_discarded
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.discard_purge_enabled:
        return 0
    return await purge_expired_discarded(session, now, settings.discard_purge_batch)


# 登记顺序即执行顺序。
JOBS = [
    ("todo_escalation", job_todo_escalation),
    ("atom_evidence_timeout", job_atom_evidence_timeout),
    ("pwc_cooldown_release", job_pwc_cooldown_release),
    ("wordlist_activation", job_wordlist_activation),
    ("discard_purge", job_discard_purge),
]
