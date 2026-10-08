"""Q43 17 池选项字典服务：列表 / upsert / 软归档（载体随 Q308 落）。

两条口径写死在这里：
- **池名是闭合集**——17 个键就是 Q40 校验器认的那 17 个（`pa_rules.WEIGHT_KEYS_17`）；
  加第 18 个池要先改 PCP 口径，不是在这张表里塞一行就算数 ⇒ 未知池 422。
- **选项内容由运营给**：docs 只定"池→选项列表"，没给任何一池的候选值，
  所以种子留空列表、由管理面回填；这里只校验形状（非空字符串、池内不重复），不校验语义。

运行期消费方（Q323 核实）：
- 「选料只能从字典选项中选」的现行强校验在 **goal 维度**——E1.1 组装
  （`final_whitelist.service._validate_goal` → GoalInvalid）与 PWC 构建
  （`model_registry.pwc_build` unknown_goals）都只接受 Q25 目的字典（ContentGoal
  活跃表）内的 goal，即 17 池中 goal 池的选料已闭环。
- 其余 16 池（action/struct/intensity/…/ending）是 PCP 权重维度，组装输入无
  自由池值字段（assemble 只收 goal/platform/slot/country），无运行期自由输入点，
  强校验无从附加；options 由运营回填后供后续分析面（PCP 重算 AI 候选对照等）消费。
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.actor import Actor
from app.core.audit import append_audit
from app.core.pool_options.models import ACTIVE, ARCHIVED, PoolOption
from app.core.pool_options.seeds import POOL_KEYS
from app.core.rbac import DICTIONARY_ADMIN, require_any_role

PLATFORM_TENANT = "_platform"


class PoolInvalid(Exception):
    pass


class PoolNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


async def list_pools(session, *, include_archived: bool = False) -> Sequence[PoolOption]:
    stmt = select(PoolOption).order_by(PoolOption.pool)
    if not include_archived:
        stmt = stmt.where(PoolOption.status == ACTIVE)
    return (await session.scalars(stmt)).all()


def _normalise_options(options: list | None) -> list[str]:
    """只校形状：必须是字符串列表、去空后非空、同一池内不重复。"""
    if options is None:
        return []
    if not isinstance(options, list):
        raise PoolInvalid("options must be a list of strings")
    cleaned: list[str] = []
    for item in options:
        if not isinstance(item, str) or not item.strip():
            raise PoolInvalid("options must be non-empty strings")
        value = item.strip()
        if value in cleaned:
            raise PoolInvalid(f"duplicate option in pool: {value}")
        cleaned.append(value)
    return cleaned


async def upsert_pool(
    session, *, pool: str, options: list | None, actor: Actor
) -> PoolOption:
    require_any_role(actor, DICTIONARY_ADMIN)
    pool = (pool or "").strip().lower()
    if pool not in POOL_KEYS:
        raise PoolInvalid(f"unknown pool: {pool!r}; the 17 pools are fixed by Q40")
    values = _normalise_options(options)
    row = await session.get(PoolOption, pool)
    if row is None:
        row = PoolOption(pool=pool)
        session.add(row)
    row.options = values
    # 显式 upsert 即（重新）启用；与 upsert_goal / upsert_language / upsert_action 同口径。
    row.status = ACTIVE
    row.updated_by = actor.id
    row.updated_at = _now()
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pool_option.upsert",
        entity_type="pool_option",
        entity_id=pool,
        detail={"options": values, "count": len(values)},
    )
    return row


async def archive_pool(session, pool: str, actor: Actor) -> PoolOption:
    require_any_role(actor, DICTIONARY_ADMIN)
    row = await session.get(PoolOption, pool)
    if row is None:
        raise PoolNotFound(pool)
    row.status = ARCHIVED
    row.updated_by = actor.id
    row.updated_at = _now()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pool_option.archive",
        entity_type="pool_option",
        entity_id=pool,
        detail={"kept_options": len(row.options)},
    )
    return row
