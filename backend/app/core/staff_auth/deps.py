"""全局 staff 认证依赖（Q178）。

挂在 FastAPI app 级 ``dependencies`` 上，每个请求在端点前执行：

- 门控关闭（默认）：直接返回，管理面维持 V1 actor 自报，零行为变化、零 DB 开销。
- 门控开启：解析 ``Authorization: Bearer``；为 staff 令牌（loom_staff_ 前缀）则
  独立短事务验真、回填 last_used_at、把人员身份写入请求级 contextvar；提供了 staff
  令牌但无效/吊销一律 401（不静默降级到自报）。
- 无令牌、或机器 Agent 令牌（loom_ 前缀，属 effect-callback/A2A）不在此拦截：
  客户与公开口不要求内部身份；内部角色闸（rbac.require_any_role）在缺认证时抛 401。

授权（角色判定）仍集中在服务层 rbac，本依赖只负责认证（authentication）。
认证 session 与端点业务事务分离（last_used 提交不裹挟业务事务），且门控关闭时
惰性返回 None、不获取连接。
"""

from collections.abc import AsyncGenerator

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, settings
from app.core.rbac import NotAuthenticated, PermissionDenied
from app.core.staff_auth import service
from app.core.staff_auth.context import get_current_staff, set_current_staff


async def get_auth_session() -> AsyncGenerator[AsyncSession | None, None]:
    """认证专用短事务；门控关闭时惰性返回 None（不获取连接）。"""
    if not settings.staff_auth_enabled:
        yield None
        return
    async with SessionLocal() as session:
        yield session


async def staff_auth_context(
    authorization: str | None = Header(default=None),
    auth_session: AsyncSession | None = Depends(get_auth_session),
) -> None:
    if not settings.staff_auth_enabled:
        return
    token = service.parse_bearer(authorization)
    if not token or not service.is_staff_token(token):
        # 无令牌（客户/公开/机器口）或非 staff 令牌（Agent Key 走各自鉴权）。
        return
    row = await service.verify_staff_key(auth_session, token)
    if row is None:
        raise NotAuthenticated("invalid or revoked staff access token")
    await auth_session.commit()
    set_current_staff(service.staff_actor(row))


def internal_gate(*roles: str):
    """门控开启时要求已认证 staff 且具备任一角色；门控关闭时 no-op。

    用于 Q88/Q109 这类**门控关有意保持开放**（无 query actor）的管理面 GET：
    不能给它们加 query actor 依赖（会破坏门控关契约），但门控开启后不应再裸奔，
    故用本依赖——关闭时完全透传，开启时缺令牌 401、角色不足 403。
    """

    def dependency() -> bool:
        if not settings.staff_auth_enabled:
            return True
        authn = get_current_staff()
        if authn is None:
            raise NotAuthenticated("staff access token required for internal operations")
        if roles and not any(r in authn.roles for r in roles):
            raise PermissionDenied(f"requires one of roles: {', '.join(roles)}")
        return True

    return dependency
