"""段9 三包「同三元组仅一个 active」的 DB 级守卫（Q288，待裁项⑦ 裁「补」丙案）。

此前唯一性只由 service 层先查后插保证（`service.py:113-124`→`PackageExists`→409），
而 0008 建 `packages` 时零唯一约束 ⇒ **并发双建无守卫**（docs/23 §8.3，Q278 勘误：
台账曾引用不存在的 `uq_package_active_triple`）。本文件钉三件事：

- 模型必须与迁移 0048 成对声明部分唯一索引（缺一边 Q207 漂移门红，这里再钉一层）；
- DB 真的拒绝重复 active（同会话两次插入 → IntegrityError），archived 孪生不拦；
- 并发形态的错误翻译：绕过 service 先查直插、再走 API 的 commit ⇒ 仍回 **409**
  （`router.py` 的 IntegrityError→409 映射；design-p2 §6 预告过的形态变更）。
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.staff_auth.deps import get_auth_session
from app.decision.layer_strategy import service
from app.decision.layer_strategy.models import Package
from app.main import app
from tests.integration.staff_tokens import bearer, issue_write_token

TRIPLE = {"product_space_id": "ps-guard", "platform": "taobao", "goal": "g_convert"}


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    app.dependency_overrides[get_auth_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


def _package(**overrides) -> Package:
    fields = {
        "kind": "csp",
        "tenant_id": "t-guard",
        "payload": {"layer_strategy": "底座选项"},
        "status": "active",
        **TRIPLE,
    }
    fields.update(overrides)
    return Package(**fields)


def test_the_partial_index_is_declared_on_the_model_not_just_the_migration() -> None:
    """迁移 0048 建索引、模型必须双写 where——这里把「成对」钉成判据。"""
    index = next(i for i in Package.__table__.indexes if i.name == "uq_packages_active_triple")
    assert index.unique
    for dialect in ("postgresql", "sqlite"):
        where = index.dialect_options[dialect]["where"]
        assert "status = 'active'" in str(where), (dialect, where)
    # 索引名刻意不复用幻影 `uq_package_active_triple`（Q272 起被误当既有事实引用 5 处）
    assert not any(i.name == "uq_package_active_triple" for i in Package.__table__.indexes)


async def test_duplicate_active_triple_is_rejected_by_the_database(session_factory) -> None:
    async with session_factory() as session:
        session.add(_package())
        await session.commit()
        session.add(_package(package_id="dup-1"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_archived_twin_does_not_block_a_new_active_row(session_factory) -> None:
    """部分索引只看 active：旧包归档后，同三元组可以再配新 active 包（重配语义）。"""
    async with session_factory() as session:
        # 同一提交里 active＋archived 同三元组共存 ⇒ 证明索引是**部分**的
        # （普通唯一索引在这里就会红）。
        session.add(_package(package_id="archived-1"))
        session.add(_package(package_id="archived-2", status="archived"))
        await session.commit()
    async with session_factory() as session:
        stored = await session.get(Package, "archived-1")
        stored.status = "archived"
        await session.commit()
    async with session_factory() as session:
        session.add(_package(package_id="fresh-1"))
        await session.commit()  # 不抛 ⇒ 索引只约束 active


async def test_concurrent_create_through_the_api_maps_the_db_conflict_to_409(
    session_factory, client, monkeypatch
) -> None:
    """service 的先查后插在并发下拦不住（两个请求都通过 select），冲突在 commit 才浮出。
    预插一行后把 service 查重「致盲」，API 的 commit 就会撞 0048 索引 ⇒ 必须仍回 409
    而不是 500（design-p2 §6 预告的并发形态变更）。"""

    async with session_factory() as session:
        session.add(_package())
        await session.commit()

    async def blind_create(session, product_space_id, body, actor):
        """与 service.create_package 相同的插入，但**跳过查重**——模拟并发窗口。"""
        item = body.item
        package = Package(
            kind=item.kind,
            tenant_id=actor.tenant_id if hasattr(actor, "tenant_id") else "t-guard",
            product_space_id=product_space_id,
            platform=item.platform,
            goal=item.goal,
            payload=item.payload,
            conf=item.conf,
            created_by=actor.id,
        )
        session.add(package)
        return package

    monkeypatch.setattr(service, "create_package", blind_create)
    resp = await client.post(
        "/api/product-spaces/ps-guard/packages",
        json={"item": {"kind": "csp", "platform": "taobao", "goal": "g_convert",
                       "payload": {"layer_strategy": "底座选项"}},
              "actor": {"id": "ops-1", "roles": ["operations"]}},
    )
    assert resp.status_code == 409, resp.text
    assert "concurrent insert" in resp.text
