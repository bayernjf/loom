"""请求级"已验真凭证"上下文（Q196 口径 B 甲）。

与 ``staff_auth.context`` 的分工：那里是 RBAC 用的**内部人员**身份（只在 staff
令牌验真通过后写入，用于判定内部角色）；这里是**任意**已验真凭证（staff PAT 或
入站 Agent Key）的统一视图，供 writeAudit 在落库前把操作人归到真实凭证。

放在独立模块是为了打破 import 环：``api_keys`` 与 ``staff_auth`` 都要写它，
而它们本身又都调用 ``append_audit``。
"""

from contextvars import ContextVar

from app.core.actor import Actor

# 凭证种类标签随审计 detail 落库，值班/对账时可分辨这条审计是"谁说了算"。
CREDENTIAL_STAFF = "staff_token"
CREDENTIAL_AGENT_KEY = "agent_key"
CREDENTIAL_NONE = "declared"

_verified: ContextVar[tuple[Actor, str] | None] = ContextVar(
    "loom_verified_credential", default=None
)


def set_verified_credential(actor: Actor, kind: str) -> None:
    _verified.set((actor, kind))


def get_verified_credential() -> tuple[Actor, str] | None:
    return _verified.get()


def reset_verified_credential() -> None:
    _verified.set(None)
