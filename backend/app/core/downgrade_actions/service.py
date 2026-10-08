"""Q38 降级动作字典服务：列表 / upsert / 软归档（载体随 Q306 落）。

字典语义（docs/02:141）＝「AI 降级建议必须从预设动作字典里选，不许自由发挥」。
本模块只管可选集本身；段 12 按结构化指令执行、以及"建议必须命中字典"的运行期强校验
随段 12 点工（规格未给执行细节，登记挂账不在此臆造）。
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.actor import Actor
from app.core.audit import append_audit
from app.core.downgrade_actions.models import ACTIVE, ARCHIVED, DowngradeAction
from app.core.rbac import DICTIONARY_ADMIN, require_any_role

PLATFORM_TENANT = "_platform"

# 动作码是大写蛇形枚举码（与 content_goals/语言清单同族），不是自由文本。
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")


class ActionInvalid(Exception):
    pass


class ActionNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


async def list_actions(
    session, *, include_archived: bool = False
) -> Sequence[DowngradeAction]:
    stmt = select(DowngradeAction).order_by(DowngradeAction.code)
    if not include_archived:
        stmt = stmt.where(DowngradeAction.status == ACTIVE)
    return (await session.scalars(stmt)).all()


async def upsert_action(
    session, *, code: str, name: str | None, why: str | None, actor: Actor
) -> DowngradeAction:
    require_any_role(actor, DICTIONARY_ADMIN)
    code = (code or "").strip().upper()
    if not CODE_PATTERN.match(code):
        raise ActionInvalid(f"code must be UPPER_SNAKE_CASE: {code!r}")
    action = await session.get(DowngradeAction, code)
    if action is None:
        action = DowngradeAction(code=code)
        session.add(action)
    action.name = (name or "").strip() or None
    action.why = (why or "").strip() or None
    # 显式 upsert 即（重新）启用；与 upsert_goal / upsert_language 复活口径一致。
    action.status = ACTIVE
    action.updated_at = _now()
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="downgrade_action.upsert",
        entity_type="downgrade_action",
        entity_id=code,
        detail={"name": action.name, "why": action.why},
    )
    return action


async def archive_action(session, code: str, actor: Actor) -> DowngradeAction:
    require_any_role(actor, DICTIONARY_ADMIN)
    action = await session.get(DowngradeAction, code)
    if action is None:
        raise ActionNotFound(code)
    action.status = ARCHIVED
    action.updated_at = _now()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="downgrade_action.archive",
        entity_type="downgrade_action",
        entity_id=code,
        detail={},
    )
    return action
