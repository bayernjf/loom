"""E1.1 `final_id` 唯一出口的运行期守卫（Q203 #34 后半）。

「`final_id` 只能由 E1.1 publishFCW 写入」在 01 PRD 与 router 模块注释里写了很多年，
但一直只是约定：任何拿到 ORM 模型的代码 `session.add(FinalContentWhitelist(...))`
都能凭空造出一条成品（本仓测试里就有 9 处这么做）。本模块把它变成运行期事实：

- ``issue_scope()`` 是一个请求/协程级作用域，只有 ``service.assemble_one``（E1.1）进入；
- ``final_content_whitelists`` 的 mapper ``before_insert`` 事件要求当前处于该作用域，
  否则抛 :class:`OutsidePublishFCW`，flush 直接失败。

覆盖边界（刻意写清，别让下一个人误以为它挡一切）：守卫挂在 **ORM flush** 上。
Core ``insert()`` / 裸 SQL / 直连数据库不经 mapper 事件，因此不在覆盖范围内——
全仓实测今日无此类写入（迁移里对这张表只有建表，无种子），
该边界由 ``test_core_insert_bypasses_the_mapper_guard`` 钉成事实而非断言。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_ISSUE_SCOPE: ContextVar[bool] = ContextVar("loom_fcw_issue_scope", default=False)


class OutsidePublishFCW(RuntimeError):
    """在 E1.1 之外写入 final_content_whitelists（协议违反，不是业务错误）。"""


def in_issue_scope() -> bool:
    return _ISSUE_SCOPE.get()


@contextmanager
def issue_scope() -> Iterator[None]:
    """唯一出口作用域；可重入（嵌套退出只撤自己那一层）。"""
    token = _ISSUE_SCOPE.set(True)
    try:
        yield
    finally:
        _ISSUE_SCOPE.reset(token)


def install(mapper) -> None:
    """把守卫挂到 ``FinalContentWhitelist`` 的 mapper 上（由 models.py 在导入时调用）。

    挂在 mapper 而非 session 上：一张表一个进程级守卫，新建 session、
    别人的 session 都绕不过去。
    """
    from sqlalchemy import event

    @event.listens_for(mapper, "before_insert")
    def _require_publish_fcw(*_args) -> None:
        if not in_issue_scope():
            raise OutsidePublishFCW(
                "final_content_whitelists 只能由 E1.1 publishFCW "
                "(app/final/final_whitelist/service.assemble_one) 写入；"
                "需要一条成品请走该服务，测试夹具请显式进 issue_scope()"
            )
