"""内容后端注册点（M4/T-M4-01）。

按名取后端，未注册 fail-closed（同 commerce ChannelRegistry 口径），
不允许静默回退到一个不可用的后端。
"""

from __future__ import annotations

from app.core.content_base.base import ContentBackend
from app.core.content_base.errors import ContentBackendUnavailable


class BackendNotRegistered(ContentBackendUnavailable):
    """请求的内容后端未注册。"""


_backends: dict[str, ContentBackend] = {}
_default_name: str | None = None


def register(name: str, backend: ContentBackend, *, make_default: bool = False) -> None:
    """注册一个命名后端；make_default 同时设为默认后端。"""
    _backends[name] = backend
    global _default_name
    if make_default or _default_name is None:
        _default_name = name


def get_backend(name: str) -> ContentBackend:
    backend = _backends.get(name)
    if backend is None:
        raise BackendNotRegistered(f"content backend not registered: {name}")
    return backend


def get_default() -> ContentBackend:
    if _default_name is None:
        raise BackendNotRegistered("no default content backend registered")
    return get_backend(_default_name)


def reset() -> None:
    """清空注册（测试隔离用）。"""
    _backends.clear()
    global _default_name
    _default_name = None
