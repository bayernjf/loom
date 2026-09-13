"""writeAudit append-only 审计写入（docs/15 §3, D3.11）。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import AuditLog

__all__ = ["append_audit"]


async def append_audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    actor_roles: list[str] | None,
    action: str,
    entity_type: str,
    entity_id: str,
    detail: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_roles=actor_roles,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
        )
    )
