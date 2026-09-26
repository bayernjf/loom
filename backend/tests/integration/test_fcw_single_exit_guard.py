"""Q203 #34 后半：`final_id` 唯一出口由注释升级为运行期守卫（docs/20 §7.4 判据 3）。

判据＝在 E1.1 publishFCW（``service.assemble_one``）之外直插
``final_content_whitelists`` 必须判红。修前实测：全仓 9 个测试文件用
``FinalContentWhitelist(...)`` + ``session.add`` 凭空造成品，没有一处报错——
「唯一出口」当时只是 router 模块注释里的一句话。

Healthy-path 反向证明不在本文件里重复：`test_fcw_api.py` 的 200 发证用例即
「装配路径仍然写得进去」的哨兵，若 service 的 ``issue_scope()`` 接线被拆掉，
那批用例会全体判红（本批已按该植入缺陷实测）。
"""

import pytest
import pytest_asyncio
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.final.final_whitelist.exit_guard import OutsidePublishFCW, issue_scope
from app.final.final_whitelist.models import FcwAssemblyTask, FinalContentWhitelist

_ROW = {
    "tenant_id": "t1",
    "product_space_id": "ps-1",
    "pws_id": "pws-1",
    "pwc_id": "pwc-1",
    "pcp_id": "pcp-1",
    "csp_package_id": "csp-1",
    "cstp_package_id": "cstp-1",
    "cep_package_id": "cep-1",
    "platform": "douyin",
    "slot_id": "slot-1",
    "goal": "种草",
    "guards_passed": True,
    "issued_by": "ops-1",
}


@pytest_asyncio.fixture
async def session_factory():
    # StaticPool：跨 session 共享同一个内存库，才能证明守卫是进程级而非会话级。
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


async def _count(session: AsyncSession) -> int:
    return await session.scalar(
        select(func.count()).select_from(FinalContentWhitelist)
    )


async def test_direct_orm_insert_outside_publish_fcw_is_rejected(session_factory):
    """§7.4 判据 3 的哨兵：拿到模型不等于能造成品。"""
    async with session_factory() as session:
        session.add(FinalContentWhitelist(final_id="fcw-direct", **_ROW))
        with pytest.raises(OutsidePublishFCW, match="E1.1"):
            await session.flush()
    async with session_factory() as probe:
        assert await _count(probe) == 0


async def test_guard_survives_a_fresh_session_and_connection(session_factory):
    """守卫挂在 mapper 上：换 session、换连接都躲不开（不是 session 事件）。"""
    async with session_factory() as first:
        with pytest.raises(OutsidePublishFCW):
            first.add(FinalContentWhitelist(final_id="fcw-2", **_ROW))
            await first.flush()
    async with session_factory() as second:
        with pytest.raises(OutsidePublishFCW):
            second.add(FinalContentWhitelist(final_id="fcw-3", **_ROW))
            await second.flush()


async def test_sanctioned_scope_writes_the_row(session_factory):
    """作用域内的写入照常成功——否则「判红」可能只是「这张表根本写不进去」。"""
    async with session_factory() as session:
        with issue_scope():
            session.add(FinalContentWhitelist(final_id="fcw-ok", **_ROW))
            await session.flush()
        await session.commit()
    async with session_factory() as probe:
        assert await _count(probe) == 1


async def test_scope_is_not_left_open_after_the_block(session_factory):
    """退出作用域必须撤销：with 块结束后再插要重新判红（防"一次打开永久放行"）。"""
    async with session_factory() as session:
        with issue_scope():
            session.add(FinalContentWhitelist(final_id="fcw-a", **_ROW))
            await session.flush()
        with pytest.raises(OutsidePublishFCW):
            session.add(FinalContentWhitelist(final_id="fcw-b", **_ROW))
            await session.flush()


async def test_other_tables_are_not_affected(session_factory):
    """守卫只钉这一张表：同包的任务表直插仍应放行（否则修过头了）。"""
    async with session_factory() as session:
        session.add(
            FcwAssemblyTask(
                task_id="task-1",
                tenant_id="t1",
                product_space_id="ps-1",
                pws_id="pws-1",
                platform="douyin",
                goal="种草",
                requested_count=1,
                status="completed",
                created_by="ops-1",
            )
        )
        await session.flush()


async def test_core_insert_bypasses_the_mapper_guard(session_factory):
    """覆盖边界的**实测事实**（不是断言）：Core/裸 SQL 写入不经 mapper 事件。

    写在这里是为了让下一个人不至于以为这道守卫挡得住一切——它挡的是"拿到 ORM
    模型顺手 add 一条"，也就是修前真实存在的那 9 处。全仓今日对这张表无 Core
    写入（迁移里只有建表、无种子），故此路径不需要额外封堵，但边界必须留痕。
    """
    async with session_factory() as session:
        await session.execute(
            insert(FinalContentWhitelist).values(final_id="fcw-core", **_ROW)
        )
        await session.commit()
    async with session_factory() as probe:
        assert await _count(probe) == 1
