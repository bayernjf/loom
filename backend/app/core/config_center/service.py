"""配置中心服务：改值即发布新版本（14 §2.4：新版本 + 原子切换 + writeAudit + 回滚）。"""

from sqlalchemy import event, select

from app.core.audit import append_audit
from app.core.config_center.cache import config_cache
from app.core.config_center.config_rules import coerce
from app.core.config_center.models import ConfigItem, ConfigItemVersion

PLATFORM_TENANT = "_platform"

# 07 §2.3：平台级管理员（Q46/Q64）；英文角色码原文未给【实现补】。
ROLE_PLATFORM_ADMIN = "platform_admin"


class RoleNotAllowed(Exception):
    pass


class ConfigKeyNotFound(Exception):
    pass


class ConfigVersionNotFound(Exception):
    pass


def _require_admin(actor) -> None:
    if ROLE_PLATFORM_ADMIN not in actor.roles:
        raise RoleNotAllowed("requires platform_admin role")


def _schedule_cache_apply(session, key: str, value) -> None:
    # 仅在事务真正提交后切换进程内快照；回滚则缓存不动。
    event.listen(
        session.sync_session,
        "after_commit",
        lambda *_: config_cache.apply({key: value}),
        once=True,
    )


async def list_items(session, *, category: str | None = None) -> list[ConfigItem]:
    stmt = select(ConfigItem).order_by(ConfigItem.category, ConfigItem.key)
    if category is not None:
        stmt = stmt.where(ConfigItem.category == category)
    return list((await session.scalars(stmt)).all())


async def get_item(session, key: str) -> ConfigItem:
    item = await session.get(ConfigItem, key)
    if item is None:
        raise ConfigKeyNotFound(key)
    return item


async def history(session, key: str) -> list[ConfigItemVersion]:
    await get_item(session, key)
    return list(
        (
            await session.scalars(
                select(ConfigItemVersion)
                .where(ConfigItemVersion.key == key)
                .order_by(ConfigItemVersion.version.desc())
            )
        ).all()
    )


async def _publish(session, item: ConfigItem, value, actor, note: str | None, action: str) -> ConfigItem:
    coerced = coerce(value, item.value_type, item.validation)
    item.value = coerced
    item.version += 1
    item.updated_by = actor.id
    session.add(
        ConfigItemVersion(
            key=item.key,
            version=item.version,
            value=coerced,
            change_note=note,
            changed_by=actor.id,
        )
    )
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action=action,
        entity_type="config_item",
        entity_id=item.key,
        detail={"version": item.version, "value": coerced, "note": note},
    )
    _schedule_cache_apply(session, item.key, coerced)
    return item


async def update_item(session, key: str, body) -> ConfigItem:
    _require_admin(body.actor)
    item = await get_item(session, key)
    return await _publish(session, item, body.value, body.actor, body.change_note, "config.update")


async def rollback_item(session, key: str, body) -> ConfigItem:
    _require_admin(body.actor)
    item = await get_item(session, key)
    target = (
        await session.scalars(
            select(ConfigItemVersion).where(
                ConfigItemVersion.key == key,
                ConfigItemVersion.version == body.target_version,
            )
        )
    ).first()
    if target is None:
        raise ConfigVersionNotFound(f"{key} v{body.target_version}")
    note = body.change_note or f"rollback to v{body.target_version}"
    return await _publish(
        session, item, target.value, body.actor, note, "config.rollback"
    )
