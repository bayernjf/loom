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

from typing import Any, NamedTuple, cast

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
    async def tenant_scoped_dependency(
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

    async def identity_dependency(
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

    dependency = tenant_scoped_dependency if tenant_bound else identity_dependency
    # 接线自检标记：路由上的 Depends 被删掉时，结构用例可据此判红。
    cast(Any, dependency).loom_requires_client_credential = True
    return dependency


def require_client_actor():
    """租户绑定口径：令牌必须 active 且绑定租户与 ``tenant_id`` 一致。"""
    return _client_dependency(tenant_bound=True)


def require_client_identity():
    """仅身份口径：任一 active 客户令牌即可（非租户作用域只读目录用）。"""
    return _client_dependency(tenant_bound=False)


class ClientOrStaffCaller(NamedTuple):
    """双闸验真结果。tenant_id 为客户令牌绑定租户；staff 令牌为 None（运营跨租户）。"""

    actor: Actor
    tenant_id: str | None


_NO_CREDENTIAL_DUAL = (
    "valid client or staff access token required (self-declared actor is not identity)"
)


def require_client_or_staff_actor(*staff_roles: str):
    """评审 P1-1：客户/运营双闸——客户令牌（loom_client_，租户绑定）或 staff 令牌
    （loom_staff_，验真且须具备 staff_roles 之一，门控关也自行验真）。

    用于同一端点被客户页与运营中台共同消费的表面（intakes、effects 回填）：
    - 客户令牌：query tenant_id 存在时校验令牌↔租户绑定（不符 401）；路径作用域
      端点由调用方按 caller.tenant_id 做行级 404。
    - staff 令牌：跨租户，角色由验真结果唯一权威（body 自报 roles 不作数）。
    缺失/无效/吊销统一 401，不区分原因。last_used_at 提交不裹挟端点业务事务。
    """
    from app.core.identity import (
        CREDENTIAL_CLIENT,
        CREDENTIAL_STAFF,
        set_verified_credential,
    )
    from app.core.rbac import require_any_role
    from app.core.staff_auth import service as staff_service

    async def dependency(
        tenant_id: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> ClientOrStaffCaller:
        token = service.parse_bearer(authorization)
        if service.is_client_token(token):
            row = await service.verify_client_key(session, token, tenant_id)
            if row is None:
                raise NotAuthenticated(_NO_CREDENTIAL_DUAL)
            await session.commit()
            actor = service.client_actor(row)
            # Q196 口径 B 甲：审计以验真凭证为准，body 自报降级为 declared_actor 备查。
            set_verified_credential(actor, CREDENTIAL_CLIENT)
            return ClientOrStaffCaller(actor, row.tenant_id)
        if staff_service.is_staff_token(token):
            staff_row = await staff_service.verify_staff_key(session, token)
            if staff_row is None:
                raise NotAuthenticated(_NO_CREDENTIAL_DUAL)
            await session.commit()
            actor = staff_service.staff_actor(staff_row)
            if staff_roles:
                require_any_role(actor, *staff_roles)
            set_verified_credential(actor, CREDENTIAL_STAFF)
            return ClientOrStaffCaller(actor, None)
        raise NotAuthenticated(_NO_CREDENTIAL_DUAL)

    # 接线自检标记：路由上的 Depends 被删掉时，结构用例可据此判红。
    cast(Any, dependency).loom_requires_client_credential = True
    return dependency
