"""Q328（D2 甲）集成测试：GET /api/admin/content/{id}/script-recheck。

口径（design-video-studio-segment-cleaning §5，D2 甲）：
- 跨租户运营只读（同 Q326 管理端成品详情口）：query actor 闸（缺 422、客户
  403）；复检对象＝FCW 表达层 CEP 包 payload 的叶子字符串（递归提取，不臆造
  键名）；复用 ccr_rules.evaluate（industry 过滤＋适用国家过滤）返回
  block_required/bans/downgrades，不改文本、不落报告；
- 未发证成品（final_id 无 FCW）/无表达层文本 → 200 text_present=false＋detail
  （复检对象不存在≠资源不存在）；ghost content → 404；
- 成片语音/字幕复检随段12 转写能力【待补】，不在本口。

create_all 不跑迁移种子；FCW 行走 fcw_rows.add_fcw（Q203 签发作用域夹具）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import CONTENT_READY, KIND_ARTICLE, ContentProduct
from app.core.compliance_wordlist.models import ComplianceWordlistEntry
from app.core.db import Base, get_session
from app.decision.layer_strategy.models import Package
from app.final.final_whitelist.models import FinalContentWhitelist
from app.main import app
from tests.integration.fcw_rows import add_fcw

OPS_Q = {"actor_id": "ops-1", "roles": ["operations"]}
CUSTOMER_Q = {"actor_id": "cust-1", "roles": []}

_FCW_KEYS = ("final_id", "tenant_id", "product_space_id", "pws_id", "pwc_id",
             "pcp_id", "csp_package_id", "cstp_package_id", "cep_package_id",
             "platform", "slot_id", "goal", "guards_passed", "issued_by")


def _fcw(final_id: str, cep_package_id: str) -> FinalContentWhitelist:
    suffix = final_id.split("-")[1]
    return FinalContentWhitelist(
        final_id=final_id,
        tenant_id="t1",
        product_space_id=f"ps-{suffix}",
        pws_id=f"pws-{suffix}",
        pwc_id=f"pwc-{suffix}",
        pcp_id=f"pcp-{suffix}",
        csp_package_id=f"csp-{suffix}",
        cstp_package_id=f"cstp-{suffix}",
        cep_package_id=cep_package_id,
        platform="douyin",
        slot_id=f"slot-{suffix}",
        goal="种草",
        guards_passed=True,
        issued_by="ops-1",
    )


def _content(content_id: str, final_id: str, ps_id: str) -> ContentProduct:
    return ContentProduct(
        content_id=content_id,
        tenant_id="t1",
        product_space_id=ps_id,
        final_id=final_id,
        goal="种草",
        platform="douyin",
        country="CN",
        kind=KIND_ARTICLE,
        language="zh-CN",
        body="正文",
        review_hits={},
        status=CONTENT_READY,
    )


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_issued(client, session_factory, *, content_id="c-1", ps_id="ps-1",
                       cep_payload=None, final_id="final-1"):
    async with session_factory() as session:
        session.add(Package(
            package_id="cep-1", kind="cep", tenant_id="t1",
            product_space_id=ps_id, platform="douyin", goal="种草",
            payload=cep_payload if cep_payload is not None else {
                "tone": "温和", "style": "口语化",
            },
            gate="approved", status="active",
        ))
        await add_fcw(session, [_fcw(final_id, "cep-1")])
        session.add(_content(content_id, final_id, ps_id))
        await session.commit()


async def test_script_recheck_clean(client, session_factory):
    await _seed_issued(client, session_factory)
    resp = await client.get("/api/admin/content/c-1/script-recheck", params=OPS_Q)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content_id"] == "c-1"
    assert body["final_id"] == "final-1"
    assert body["text_present"] is True
    assert body["text_length"] > 0
    assert body["status"] == "clean"
    assert body["block_required"] is False
    assert body["bans"] == []
    assert body["downgrades"] == []


async def test_script_recheck_blocks_banned_term(client, session_factory):
    async with session_factory() as session:
        session.add(ComplianceWordlistEntry(
            word="绝对安全", level="critical", action="ban",
        ))
        await session.commit()
    await _seed_issued(client, session_factory, cep_payload={"tone": "绝对安全且温和"})
    resp = await client.get("/api/admin/content/c-1/script-recheck", params=OPS_Q)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text_present"] is True
    assert body["block_required"] is True
    assert any(b["word"] == "绝对安全" for b in body["bans"])


async def test_script_recheck_fcw_missing_returns_text_present_false(client, session_factory):
    async with session_factory() as session:
        session.add(_content("c-2", "ghost-final", "ps-2"))
        await session.commit()
    resp = await client.get("/api/admin/content/c-2/script-recheck", params=OPS_Q)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text_present"] is False
    assert body["detail"] == "fcw_missing"
    assert body["block_required"] is False


async def test_script_recheck_no_text_payload(client, session_factory):
    await _seed_issued(client, session_factory, cep_payload={"goals": [], "meta": {"k": 1}})
    resp = await client.get("/api/admin/content/c-1/script-recheck", params=OPS_Q)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text_present"] is False
    assert body["detail"] == "no_script_text"


async def test_script_recheck_ghost_content_404(client):
    resp = await client.get("/api/admin/content/no-such/script-recheck", params=OPS_Q)
    assert resp.status_code == 404, resp.text


async def test_script_recheck_rejects_customer(client, session_factory):
    await _seed_issued(client, session_factory)
    resp = await client.get("/api/admin/content/c-1/script-recheck", params=CUSTOMER_Q)
    assert resp.status_code == 403, resp.text


async def test_script_recheck_requires_actor(client, session_factory):
    await _seed_issued(client, session_factory)
    resp = await client.get("/api/admin/content/c-1/script-recheck")
    assert resp.status_code == 422, resp.text
