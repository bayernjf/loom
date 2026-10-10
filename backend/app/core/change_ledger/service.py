"""变更-回滚清单（Rollback Center 甲案，Q334）：只读聚合面。

design-v3-rollback-center §3.1 甲＋§3.2 甲-1：从 audit_logs 派生读取五套既有
版本/撤销机制的变更事件，**不落新表、不发明第六套回滚语义**。每笔只回答三件事：
改了什么（action/entity）、能不能撤（rollbackability）、去哪撤（ops_surface，
一跳直达既有操作面——配置回滚口 / PWS 重冻 / FCW revoke / 词库再编辑）。
历史 append-only 红线不动：本面不产生任何写。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import AuditLog

# 机制 → 该机制纳入聚合的 audit action 集合（与 produce 侧逐字对齐，改这里要先查生产端）。
MECHANISM_ACTIONS: dict[str, tuple[str, ...]] = {
    "config_center": ("config.update", "config.rollback"),
    "pws": ("pws.freeze", "pws.refreeze", "pws.revoke"),
    "fcw": ("fcw.issued", "fcw.revoke"),
    "wordlist": ("wl.create", "wl.update", "wl.archive"),
    "skill_prompt": ("skill_prompt.publish",),
}

# 可回滚性分级（沿用各机制既有语义，不新增统一分级）：
# - rollbackable：有现成回滚口（配置：PUT /api/admin/config/{key}/rollback）
# - revoke_reissue：只能作废＋重冻/再发证（PWS revoke→重冻、FCW revoke→E1.1）
# - reedit_only：无版本，只能再编辑（词库）
# - no_surface：回滚操作面未建（skill_prompt 版本，design §3.1 乙 待裁）
_ROLLBACKABILITY: dict[str, tuple[str, str]] = {
    "config.update": ("rollbackable", "PUT /api/admin/config/{key}/rollback"),
    "config.rollback": ("rollbackable", "PUT /api/admin/config/{key}/rollback"),
    "pws.freeze": ("revoke_reissue", "POST /api/pws/{pws_id}/revoke 后走重冻"),
    "pws.refreeze": ("revoke_reissue", "POST /api/pws/{pws_id}/revoke 后走重冻"),
    "pws.revoke": ("revoke_reissue", "按 Q32 作废后可重冻新版（E1.1 不追溯已发布）"),
    "fcw.issued": ("revoke_reissue", "POST /api/admin/fcw/{final_id}/revoke"),
    "fcw.revoke": ("revoke_reissue", "复用走 E1.1 再发证（组装台「复用」预填）"),
    "wl.create": ("reedit_only", "词库无版本，PUT /api/admin/compliance-wordlist/{id} 再编辑"),
    "wl.update": ("reedit_only", "词库无版本，PUT /api/admin/compliance-wordlist/{id} 再编辑"),
    "wl.archive": ("reedit_only", "词库无版本，PUT /api/admin/compliance-wordlist/{id} 再编辑"),
    "skill_prompt.publish": ("no_surface", "Prompt 版本回滚操作面随 design §3.1 乙 待裁"),
}

_ACTION_TO_MECHANISM = {
    action: mechanism
    for mechanism, actions in MECHANISM_ACTIONS.items()
    for action in actions
}

ALL_ACTIONS = tuple(_ACTION_TO_MECHANISM)


def _mechanism_of(action: str) -> str:
    return _ACTION_TO_MECHANISM.get(action, "unknown")


async def list_changes(
    session: AsyncSession,
    *,
    mechanism: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """按时间倒序列出五机制的变更事件；mechanism 过滤为空则全量。"""
    actions = MECHANISM_ACTIONS.get(mechanism, ()) if mechanism else ALL_ACTIONS
    if mechanism and mechanism not in MECHANISM_ACTIONS:
        return {"total": 0, "items": []}
    base = select(AuditLog).where(AuditLog.action.in_(actions))
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (
        await session.scalars(
            base.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = []
    for row in rows:
        rollbackability, ops_surface = _ROLLBACKABILITY.get(
            row.action, ("unknown", "")
        )
        items.append(
            {
                "id": row.id,
                "tenant_id": row.tenant_id,
                "action": row.action,
                "mechanism": _mechanism_of(row.action),
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "actor_id": row.actor_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "rollbackability": rollbackability,
                "ops_surface": ops_surface,
                "detail": row.detail or {},
            }
        )
    return {"total": int(total or 0), "items": items}
