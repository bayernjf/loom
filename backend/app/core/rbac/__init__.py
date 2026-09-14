"""RBAC 红线收口（M10 切片 d，Q75）：角色常量与统一角色闸。

角色码沿用 docs/07 §2.3 / 09 D8 的英文【实现补】码；闸放在服务层（定时调度等
系统内部调用绕过 HTTP，不经此闸），路由统一把 PermissionDenied 映射为 403。
"""

from app.core.actor import Actor

OPERATIONS = "operations"
PRODUCT_REVIEWER = "product_reviewer"
DICTIONARY_ADMIN = "dictionary_admin"
INTERNAL_COMPLIANCE = "internal_compliance"
WHITELIST_OWNER = "whitelist_owner"
PLATFORM_ADMIN = "platform_admin"


class PermissionDenied(Exception):
    pass


def require_any_role(actor: Actor, *roles: str) -> None:
    if not any(role in actor.roles for role in roles):
        raise PermissionDenied(f"requires one of roles: {', '.join(roles)}")
