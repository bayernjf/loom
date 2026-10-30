"""客户内容端点的 FastAPI 认证依赖（P0，2026-10-30）。

挂到客户内容端点上：必须携带 ``Authorization: Bearer loom_client_...``。两种口径：

- :func:`require_client_actor`（租户绑定）：令牌绑定租户与请求 ``tenant_id`` 一致，
  否则 401。用于列表/详情/裁决/正文编辑等**租户作用域**端点——归属锚点是令牌，
  query ``tenant_id`` 只作一致性交叉校验，不再是身份来源。
- :func:`require_client_identity`（仅身份）：任一 active 客户令牌即可，不绑租户。
  用于 ``GET /api/content/languages`` 这类**非租户作用域**的客户只读目录。

返回的已认证 :class:`Actor` 携带 ``whitelist_owner`` 角色，调用方用它覆盖请求体
自报的 ``actor``——自报身份不再作数。验签不区分失败原因（缺失/无效/吊销/租户不符
统一 401），避免凭证探测与跨租户存在性探针。
"""

from fastapi import Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.client_auth import service
from app.core.db import get_session
from app.core.rbac import NotAuthenticated

_NO_CREDENTIAL = (
    "valid client access token required (self-declared actor is not identity)"
)
_NO_CREDENTIAL_TENANT = (
    "valid client access token for this tenant required "
    "(self-declared actor is not identity)"
)


def _client_dependency(*, tenant_bound: bool):
    if tenant_bound:
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
                raise NotAuthenticated(_NO_CREDENTIAL_TENANT)
            # 独立 session 内只有 last_used_at 回填，提交它不裹挟端点业务事务。
            await session.commit()
            return service.client_actor(row)
    else:
        async def dependency(
            authorization: str | None = Header(default=None),
            session: AsyncSession = Depends(get_session),
        ) -> Actor:
            token = service.parse_bearer(authorization)
            row = (
                await service.verify_client_key(session, token, None)
                if token
                else None
            )
            if row is None:
                raise NotAuthenticated(_NO_CREDENTIAL)
            await session.commit()
            return service.client_actor(row)

    # 接线自检标记：路由上的 Depends 被删掉时，结构用例可据此判红。
    dependency.loom_requires_client_credential = True
    return dependency


def require_client_actor():
    """租户绑定口径：令牌必须 active 且绑定租户与 ``tenant_id`` 一致。"""
    return _client_dependency(tenant_bound=True)


def require_client_identity():
    """仅身份口径：任一 active 客户令牌即可（非租户作用域只读目录用）。"""
    return _client_dependency(tenant_bound=False)
