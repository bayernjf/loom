"""客户决策端点的 FastAPI 认证依赖（P0，2026-10-30）。

挂到客户内容决策端点上：必须携带 ``Authorization: Bearer loom_client_...``，且令牌
绑定租户与请求 ``tenant_id`` 一致，否则 401。返回的已认证 :class:`Actor` 携带
``whitelist_owner`` 角色，调用方用它覆盖请求体自报的 ``actor``——自报身份不再作数。
"""

from fastapi import Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.client_auth import service
from app.core.db import get_session
from app.core.rbac import NotAuthenticated

_NO_CREDENTIAL = (
    "valid client access token for this tenant required "
    "(self-declared actor is not identity)"
)


def require_client_actor():
    async def dependency(
        tenant_id: str = Query(min_length=1),
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> Actor:
        token = service.parse_bearer(authorization)
        row = (
            await service.verify_client_key(session, token, tenant_id)
            if token
            else None
        )
        if row is None:
            raise NotAuthenticated(_NO_CREDENTIAL)
        # 独立 session 内只有 last_used_at 回填，提交它不裹挟端点业务事务。
        await session.commit()
        return service.client_actor(row)

    # 接线自检标记：路由上的 Depends 被删掉时，结构用例可据此判红。
    dependency.loom_requires_client_credential = True
    return dependency
