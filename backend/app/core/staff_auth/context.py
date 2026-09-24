"""请求级已认证内部人员上下文（Q178）。

全局认证依赖（deps.staff_auth_context）在门控开启且 Bearer staff 令牌验真通过后，
把人员身份写入本 contextvar；服务层统一角色闸 ``rbac.require_any_role`` 在判定
内部角色时读取它，从而以令牌身份为准、忽略 HTTP 自报 roles。依赖与端点/服务在
同一请求 task 内执行，contextvar 天然请求隔离，请求结束随 task 丢弃。
"""

from contextvars import ContextVar

from app.core.actor import Actor

_current_staff: ContextVar[Actor | None] = ContextVar("loom_current_staff", default=None)


def set_current_staff(actor: Actor) -> None:
    _current_staff.set(actor)


def get_current_staff() -> Actor | None:
    return _current_staff.get()


def reset_current_staff() -> None:
    _current_staff.set(None)
