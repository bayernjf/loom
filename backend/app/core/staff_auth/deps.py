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

from app.core.actor import Actor
from app.core.db import SessionLocal, settings
from app.core.identity import (
    CREDENTIAL_STAFF,
    reset_verified_credential,
    set_verified_credential,
)
from app.core.rbac import NotAuthenticated, PermissionDenied
from app.core.staff_auth import service
from app.core.staff_auth.context import get_current_staff, set_current_staff


async def get_auth_session(
    authorization: str | None = Header(default=None),
) -> AsyncGenerator[AsyncSession | None, None]:
    """认证专用短事务；无凭证可验时惰性返回 None（不获取连接）。

    Q203：门控关闭但请求带了 Bearer 时也必须给连接——E1.1 写口
    （:func:`require_internal_actor`）在门控关下仍要自行验真，拿不到 None。
    """
    if not settings.staff_auth_enabled and not service.parse_bearer(authorization):
        yield None
        return
    async with SessionLocal() as session:
        yield session


async def staff_auth_context(
    authorization: str | None = Header(default=None),
    auth_session: AsyncSession | None = Depends(get_auth_session),
) -> None:
    # 每个请求从"无凭证"起步：即便 ASGI 实现复用了同一 context 副本，也不会有
    # 上一请求的凭证泄漏进本请求的审计。
    reset_verified_credential()
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
    actor = service.staff_actor(row)
    set_current_staff(actor)
    # Q196 口径 B 甲：审计口看的是"任意已验真凭证"，不只 staff。
    set_verified_credential(actor, CREDENTIAL_STAFF)


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


_NO_CREDENTIAL = "verified staff access token required (self-declared role is not identity)"


def require_internal_actor(*roles: str):
    """E1.1 发证写口专用：**不看全局门控**，必须有已验真的 staff 令牌才放行（Q203 #34）。

    与 :func:`internal_gate` 正好相反——那个在门控关时透传以维持 V1 自报口径；本依赖在
    门控关时自行完成验真，所以"正文里自报 operations"在任何默认部署形态下都不足以签发
    `final_id`。返回已验真身份，调用方用它覆盖正文自报的 actor（与
    ``rbac.require_any_role`` 门控开时的覆盖口径一致），审计口（Q196）也经 contextvar
    拿到真实人员。

    代价写清：这两个口从此不再有"无凭证也能跑"的路径，脚本/测试须先按 Q178 引导流程
    签发一枚 staff 令牌。
    """

    async def dependency(
        authorization: str | None = Header(default=None),
        auth_session: AsyncSession | None = Depends(get_auth_session),
    ) -> Actor:
        if settings.staff_auth_enabled:
            authn = get_current_staff()
            if authn is None:
                raise NotAuthenticated(_NO_CREDENTIAL)
            actor = authn
        else:
            token = service.parse_bearer(authorization)
            if not service.is_staff_token(token):
                raise NotAuthenticated(_NO_CREDENTIAL)
            # 带 Bearer 时 get_auth_session 必然给连接；拿不到即接线被改坏。
            assert auth_session is not None
            row = await service.verify_staff_key(auth_session, token)
            if row is None:
                raise NotAuthenticated("invalid or revoked staff access token")
            await auth_session.commit()
            actor = service.staff_actor(row)
            set_current_staff(actor)
            set_verified_credential(actor, CREDENTIAL_STAFF)
        if roles and not any(r in actor.roles for r in roles):
            raise PermissionDenied(f"requires one of roles: {', '.join(roles)}")
        return actor

    # 接线自检标记：路由上的 Depends 被删掉时，test_fcw_api 的结构用例判红。
    # （行为用例当然也会红，但那条只会说"200 不是 401"，定位不到是接线掉了。）
    dependency.loom_requires_internal_credential = roles
    return dependency
