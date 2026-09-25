"""writeAudit append-only 审计写入（docs/15 §3, D3.11）。

Q196 口径 B 甲：本函数是**全仓唯一**审计落库口，故"凭证优先于自报"在这里一次性
收口——只要本次请求验真过凭证（staff PAT / 入站 Agent Key），审计里的
``actor_id``/``actor_roles`` 一律取凭证身份；调用方自报的身份降级为兼容读，仅在
与凭证不一致时以 ``declared_actor`` 留在 detail 里备查。未被任何凭证保护的口
（Q196 口径 C 甲：beta 期客户侧无登录）保持原样，但 ``_actor_via`` 明写
``declared``，让对账方能分辨这条审计的身份是谁给的。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.identity import CREDENTIAL_NONE, get_verified_credential
from app.core.models import AuditLog

__all__ = ["append_audit", "audit_identity"]


def audit_identity(
    declared_id: str | None, declared_roles: list[str] | None
) -> tuple[str | None, list[str] | None, str, dict]:
    """按"凭证 > 自报"定出应写入审计的身份，并给出留痕字段。

    返回 ``(actor_id, actor_roles, via, extra_detail)``；``extra_detail`` 只在
    凭证确实推翻了自报值时才带 ``declared_actor``，避免给正常路径添噪。
    """

    verified = get_verified_credential()
    if verified is None:
        return declared_id, declared_roles, CREDENTIAL_NONE, {}
    actor, kind = verified
    declared = Actor(id=declared_id or "", roles=list(declared_roles or []))
    extra: dict = {}
    if declared.id != actor.id or sorted(declared.roles) != sorted(actor.roles):
        extra["declared_actor"] = {"id": declared.id, "roles": declared.roles}
    return actor.id, list(actor.roles), kind, extra


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
    resolved_id, resolved_roles, via, extra = audit_identity(actor_id, actor_roles)
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=resolved_id,
            actor_roles=resolved_roles,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail={**(detail or {}), **extra, "_actor_via": via},
        )
    )
