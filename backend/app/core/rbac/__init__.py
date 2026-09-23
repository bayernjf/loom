"""RBAC 红线收口（M10 切片 d，Q75；Q178 接入人员令牌真实认证）。

角色码沿用 docs/07 §2.3 / 09 D8 的英文【实现补】码；闸放在服务层（定时调度等
系统内部调用绕过 HTTP，不经此闸），路由统一把 PermissionDenied 映射为 403、
NotAuthenticated 映射为 401。

Q178：``LOOM_STAFF_AUTH_ENABLED`` 开启后，凡要求**内部角色**的闸一律以请求级已
认证人员（staff PAT，见 staff_auth.context）为准——缺失认证抛 NotAuthenticated(401)、
角色不足抛 PermissionDenied(403)，并就地把传入的自报 actor 覆盖为认证身份（使后续
审计 actor_id/roles 落到真实人员，自报提权彻底失效）。客户角色（whitelist_owner）
与门控关闭时维持 V1 自报口径不变。
"""

from app.core.actor import Actor
from app.core.db import settings
from app.core.staff_auth.context import get_current_staff

OPERATIONS = "operations"
PRODUCT_REVIEWER = "product_reviewer"
DICTIONARY_ADMIN = "dictionary_admin"
INTERNAL_COMPLIANCE = "internal_compliance"
WHITELIST_OWNER = "whitelist_owner"
PLATFORM_ADMIN = "platform_admin"

# 内部员工角色（由 staff PAT 认证）；客户角色 whitelist_owner 不在此列。
INTERNAL_ROLES = frozenset(
    {
        OPERATIONS,
        PRODUCT_REVIEWER,
        DICTIONARY_ADMIN,
        INTERNAL_COMPLIANCE,
        PLATFORM_ADMIN,
    }
)


class PermissionDenied(Exception):
    pass


class NotAuthenticated(Exception):
    """门控开启但内部端点缺少有效 staff 令牌（→401）。"""


def require_any_role(actor: Actor, *roles: str) -> None:
    if settings.staff_auth_enabled and any(r in INTERNAL_ROLES for r in roles):
        authn = get_current_staff()
        if authn is None:
            raise NotAuthenticated(
                "staff access token required for internal operations"
            )
        if not any(role in authn.roles for role in roles):
            raise PermissionDenied(f"requires one of roles: {', '.join(roles)}")
        # 以认证身份覆盖自报身份：后续业务与审计（append_audit actor_id/roles）
        # 都落到真实人员，HTTP 自报的 id/roles 在门控开启时彻底失效。
        actor.id = authn.id
        actor.roles = list(authn.roles)
        return
    if not any(role in actor.roles for role in roles):
        raise PermissionDenied(f"requires one of roles: {', '.join(roles)}")
