"""内部运营个人令牌的签发/吊销/验签（Q178，甲案 PAT）。

复用 Q88 ``api_keys.service`` 的 SHA-256 哈希与 Bearer 解析原语，但明文前缀刻意
区分为 ``loom_staff_``（机器 Agent Key 为 ``loom_``），两类凭证分表、不可互换。
签发/吊销为 platform_admin 红线；验签不区分失败原因（缺失/无效/吊销一律 401），
避免探测侧信道。
"""

import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.api_keys.service import hash_key, parse_bearer
from app.core.audit import append_audit
from app.core.rbac import (
    DICTIONARY_ADMIN,
    INTERNAL_COMPLIANCE,
    OPERATIONS,
    PLATFORM_ADMIN,
    PRODUCT_REVIEWER,
    require_any_role,
)
from app.core.staff_auth.models import StaffApiKey

PLATFORM_TENANT = "_platform"
# 人员令牌前缀，与机器 Agent Key（loom_）区分；验签按前缀分域、分表。
_KEY_PREFIX = "loom_staff_"
_PREFIX_SHOWN = 12

# 人员令牌可绑定的内部角色（不含客户角色 whitelist_owner）。
INTERNAL_STAFF_ROLES = frozenset(
    {
        OPERATIONS,
        PLATFORM_ADMIN,
        PRODUCT_REVIEWER,
        DICTIONARY_ADMIN,
        INTERNAL_COMPLIANCE,
    }
)


class StaffKeyNotFound(Exception):
    pass


def generate_staff_key() -> tuple[str, str, str]:
    """返回 (明文令牌, sha256 hex, 展示前缀)。明文仅签发时出现一次。"""
    plaintext = _KEY_PREFIX + secrets.token_urlsafe(30)
    return plaintext, hash_key(plaintext), plaintext[:_PREFIX_SHOWN]


def is_staff_token(token: str | None) -> bool:
    return bool(token) and token.startswith(_KEY_PREFIX)


def normalize_roles(roles: list[str]) -> list[str]:
    """校验并去重保序角色列表；空/含未知角色一律 ValueError（→422）。"""
    cleaned: list[str] = []
    for role in roles or []:
        if role not in INTERNAL_STAFF_ROLES:
            raise ValueError(f"unknown or non-internal role: {role}")
        if role not in cleaned:
            cleaned.append(role)
    if not cleaned:
        raise ValueError("staff token must bind at least one internal role")
    return cleaned


async def issue_staff_key(
    session: AsyncSession,
    *,
    staff_id: str,
    staff_name: str,
    roles: list[str],
    actor: Actor,
) -> tuple[StaffApiKey, str]:
    require_any_role(actor, PLATFORM_ADMIN)
    sid = (staff_id or "").strip()
    sname = (staff_name or "").strip()
    if not sid:
        raise ValueError("staff_id must not be empty")
    if not sname:
        raise ValueError("staff_name must not be empty")
    bound_roles = normalize_roles(roles)
    plaintext, key_hash, key_prefix = generate_staff_key()
    row = StaffApiKey(
        staff_id=sid,
        staff_name=sname,
        roles=bound_roles,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_by=actor.id,
    )
    session.add(row)
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="staff_api_key.issue",
        entity_type="staff_api_key",
        entity_id=row.key_id,
        detail={
            "staff_id": sid,
            "staff_name": sname,
            "roles": bound_roles,
            "key_prefix": key_prefix,
        },
    )
    return row, plaintext


async def list_staff_keys(
    session: AsyncSession, *, include_revoked: bool = False
) -> list[StaffApiKey]:
    stmt = select(StaffApiKey).order_by(StaffApiKey.created_at.desc())
    if not include_revoked:
        stmt = stmt.where(StaffApiKey.status == "active")
    return list((await session.scalars(stmt)).all())


async def revoke_staff_key(
    session: AsyncSession, key_id: str, actor: Actor
) -> StaffApiKey:
    require_any_role(actor, PLATFORM_ADMIN)
    row = await session.get(StaffApiKey, key_id)
    if row is None:
        raise StaffKeyNotFound(key_id)
    if row.status == "active":
        row.status = "revoked"
        row.revoked_by = actor.id
        row.revoked_at = datetime.now(UTC)
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="staff_api_key.revoke",
        entity_type="staff_api_key",
        entity_id=key_id,
        detail={"staff_id": row.staff_id, "staff_name": row.staff_name},
    )
    return row


async def verify_staff_key(
    session: AsyncSession, plaintext: str | None
) -> StaffApiKey | None:
    """命中 active 令牌则回填 last_used_at 并返回行；否则 None（不区分失败原因）。"""
    if not is_staff_token(plaintext):
        return None
    stmt = select(StaffApiKey).where(
        StaffApiKey.key_hash == hash_key(plaintext),
        StaffApiKey.status == "active",
    )
    row = (await session.scalars(stmt)).first()
    if row is None:
        return None
    row.last_used_at = datetime.now(UTC)
    return row


def staff_actor(row: StaffApiKey) -> Actor:
    return Actor(id=row.staff_id, roles=list(row.roles))


__all__ = [
    "INTERNAL_STAFF_ROLES",
    "PLATFORM_TENANT",
    "StaffKeyNotFound",
    "generate_staff_key",
    "is_staff_token",
    "issue_staff_key",
    "list_staff_keys",
    "normalize_roles",
    "parse_bearer",
    "revoke_staff_key",
    "staff_actor",
    "verify_staff_key",
]
