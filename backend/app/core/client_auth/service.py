"""客户访问令牌的签发/吊销/验签（P0，2026-10-30）。

复用 staff/agent key 的 SHA-256 哈希与 Bearer 解析原语，明文前缀刻意区分为
``loom_client_``，三类凭证分表、不可互换。签发/吊销为内部运营红线
（platform_admin | operations）；验签不区分失败原因（缺失/无效/吊销/租户不符
一律 None → 401），避免凭证探测侧信道。
"""

import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.api_keys.service import hash_key, parse_bearer
from app.core.audit import append_audit
from app.core.client_auth.models import ClientAccessToken
from app.core.rbac import OPERATIONS, PLATFORM_ADMIN, WHITELIST_OWNER, require_any_role

# 客户令牌前缀，与 staff（loom_staff_）、机器 Agent Key（loom_）区分。
_KEY_PREFIX = "loom_client_"
_PREFIX_SHOWN = 12


class ClientKeyNotFound(Exception):
    pass


def generate_client_key() -> tuple[str, str, str]:
    """返回 (明文令牌, sha256 hex, 展示前缀)。明文仅签发时出现一次。"""
    plaintext = _KEY_PREFIX + secrets.token_urlsafe(30)
    return plaintext, hash_key(plaintext), plaintext[:_PREFIX_SHOWN]


def is_client_token(token: str | None) -> bool:
    return token is not None and token.startswith(_KEY_PREFIX)


async def issue_client_key(
    session: AsyncSession,
    *,
    tenant_id: str,
    client_name: str,
    actor: Actor,
) -> tuple[ClientAccessToken, str]:
    # 内部运营才能为某租户签发客户令牌。
    require_any_role(actor, PLATFORM_ADMIN, OPERATIONS)
    tid = tenant_id.strip()
    cname = client_name.strip()
    if not tid:
        raise ValueError("tenant_id must not be empty")
    if not cname:
        raise ValueError("client_name must not be empty")
    plaintext, key_hash, key_prefix = generate_client_key()
    row = ClientAccessToken(
        tenant_id=tid,
        client_name=cname,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_by=actor.id,
    )
    session.add(row)
    await session.flush()
    await append_audit(
        session,
        tenant_id=tid,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="client_access_token.issue",
        entity_type="client_access_token",
        entity_id=row.token_id,
        detail={"client_name": cname, "key_prefix": key_prefix},
    )
    return row, plaintext


async def list_client_keys(
    session: AsyncSession,
    *,
    tenant_id: str | None = None,
    include_revoked: bool = False,
) -> list[ClientAccessToken]:
    stmt = select(ClientAccessToken).order_by(
        ClientAccessToken.created_at.desc()
    )
    if tenant_id is not None:
        stmt = stmt.where(ClientAccessToken.tenant_id == tenant_id)
    if not include_revoked:
        stmt = stmt.where(ClientAccessToken.status == "active")
    return list((await session.scalars(stmt)).all())


async def revoke_client_key(
    session: AsyncSession, token_id: str, actor: Actor
) -> ClientAccessToken:
    require_any_role(actor, PLATFORM_ADMIN, OPERATIONS)
    row = await session.get(ClientAccessToken, token_id)
    if row is None:
        raise ClientKeyNotFound(token_id)
    if row.status == "active":
        row.status = "revoked"
        row.revoked_by = actor.id
        row.revoked_at = datetime.now(UTC)
    await append_audit(
        session,
        tenant_id=row.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="client_access_token.revoke",
        entity_type="client_access_token",
        entity_id=token_id,
        detail={"client_name": row.client_name},
    )
    return row


async def verify_client_key(
    session: AsyncSession, plaintext: str | None, tenant_id: str | None = None
) -> ClientAccessToken | None:
    """命中 active 且租户一致的令牌则回填 last_used_at 并返回行；否则 None。

    前缀不符/哈希未命中/已吊销/租户归属不一致统一返回 None，不区分原因，
    避免凭证探测与跨租户存在性探针。``tenant_id=None`` 为仅身份口径
    （非租户作用域只读目录）：任一 active 客户令牌即命中，不按租户过滤。
    """
    if plaintext is None or not is_client_token(plaintext):
        return None
    stmt = select(ClientAccessToken).where(
        ClientAccessToken.key_hash == hash_key(plaintext),
        ClientAccessToken.status == "active",
    )
    if tenant_id is not None:
        stmt = stmt.where(ClientAccessToken.tenant_id == tenant_id)
    row = (await session.scalars(stmt)).first()
    if row is None:
        return None
    row.last_used_at = datetime.now(UTC)
    return row


def client_actor(row: ClientAccessToken) -> Actor:
    """认证身份：客户标识作 actor.id，携带 whitelist_owner 角色。"""
    return Actor(id=row.client_name, roles=[WHITELIST_OWNER])


__all__ = [
    "ClientKeyNotFound",
    "client_actor",
    "generate_client_key",
    "is_client_token",
    "issue_client_key",
    "list_client_keys",
    "parse_bearer",
    "revoke_client_key",
    "verify_client_key",
]
