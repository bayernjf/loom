"""FCW 成品行的测试夹具入口（Q203 #34 后半配套）。

``final_content_whitelists`` 自 Q203 起有运行期「唯一出口」守卫：只有 E1.1
publishFCW（``service.assemble_one``）的签发作用域内允许 flush 成品行，
其余 ``session.add(FinalContentWhitelist(...))`` 一律判红。

真实发证路径由 ``test_fcw_api.py`` 的 200 用例覆盖；本模块只服务另一类需求——
「我要库里先有一条成品，然后再测别的东西」（内容页/导出/丢弃/多语言等）。这类夹具
必须**显式声明**自己在伪造签发作用域，而不是悄悄绕过守卫，所以统一走这里。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.final.final_whitelist import exit_guard


async def add_fcw(session: AsyncSession, rows: list) -> None:
    """把成品行写入会话并在签发作用域内 flush（之后的 commit 由调用方负责）。"""
    session.add_all(rows)
    with exit_guard.issue_scope():
        await session.flush()
