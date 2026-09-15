"""入站 Agent Key 的签发/吊销/验签（Q88；段13 effect-callback 的鉴权前置半套）。

V1 无受保护业务端点（POST /api/effect-callback 随段13/P3 V2，05 §1.1.1），
本模块提供验签依赖以备该端点复用；测试以服务层与 HTTP 治理端点自证。
"""

import hashlib
import secrets
from datetime import UTC, datetime

from fastapi import Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.api_keys.models import AgentApiKey
from app.core.audit import append_audit
from app.core.rbac import PLATFORM_ADMIN, require_any_role

PLATFORM_TENANT = "_platform"
_KEY_PREFIX = "loom_"
_PREFIX_SHOWN = 12


class AgentKeyNotFound(Exception):
    pass


def generate_key() -> tuple[str, str, str]:
    """返回 (明文 Key, sha256 hex, 展示前缀)。明文仅签发时出现一次。"""
    plaintext = _KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext, hash_key(plaintext), plaintext[:_PREFIX_SHOWN]


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def parse_bearer(authorization: str | None) -> str | None:
    """从 Authorization 头取 Bearer token；格式不符返回 None。"""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        return None
    token = parts[1].strip()
    return token or None


async def issue_key(session: AsyncSession, name: str, actor: Actor) -> tuple[AgentApiKey, str]:
    require_any_role(actor, PLATFORM_ADMIN)
    if not name or not name.strip():
        raise ValueError("agent key name must not be empty")
    plaintext, key_hash, key_prefix = generate_key()
    row = AgentApiKey(
        name=name.strip(),
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
        action="agent_api_key.issue",
        entity_type="agent_api_key",
        entity_id=row.key_id,
        detail={"name": row.name, "key_prefix": key_prefix},
    )
    return row, plaintext


async def list_keys(session: AsyncSession, *, include_revoked: bool = False) -> list[AgentApiKey]:
    stmt = select(AgentApiKey).order_by(AgentApiKey.created_at.desc())
    if not include_revoked:
        stmt = stmt.where(AgentApiKey.status == "active")
    return list((await session.scalars(stmt)).all())


async def revoke_key(session: AsyncSession, key_id: str, actor: Actor) -> AgentApiKey:
    require_any_role(actor, PLATFORM_ADMIN)
    row = await session.get(AgentApiKey, key_id)
    if row is None:
        raise AgentKeyNotFound(key_id)
    if row.status == "active":
        row.status = "revoked"
        row.revoked_by = actor.id
        row.revoked_at = datetime.now(UTC)
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="agent_api_key.revoke",
        entity_type="agent_api_key",
        entity_id=key_id,
        detail={"name": row.name},
    )
    return row


async def verify_key(session: AsyncSession, plaintext: str) -> AgentApiKey | None:
    """验签：哈希命中且未吊销才返回行；顺手记 last_used_at（调用方提交）。

    未知/已吊销/空串一律 None，不区分原因，避免凭证探测侧信道。
    """
    if not plaintext:
        return None
    row = (
        await session.scalars(
            select(AgentApiKey).where(AgentApiKey.key_hash == hash_key(plaintext))
        )
    ).one_or_none()
    if row is None or row.status != "active":
        return None
    row.last_used_at = datetime.now(UTC)
    return row


async def require_agent_key(
    session: AsyncSession,
    authorization: str | None = Header(default=None),
) -> AgentApiKey:
    """未来 /api/effect-callback 等入站端点复用的 Bearer 验签依赖（401）。"""
    token = parse_bearer(authorization)
    row = await verify_key(session, token) if token else None
    if row is None:
        raise HTTPException(status_code=401, detail="invalid or revoked agent API key")
    return row
