"""段11 FCW 冻结管理集成测试（Q251，design-fcw-freeze-management §3.1–3.3）。

覆盖六项裁决的契约面：
- a（final_id 级版本快照）：assemble 即落 FcwSnapshot（frozen/is_active/v1，
  snapshot＝6 路输入引用＋score＋guards）＋fcw_freeze_logs freeze 事件；
- d（不可变强制）：exit_guard 扩 before_update/before_delete，已发证行
  UPDATE/DELETE 判红；
- b（回滚 A 案）：POST /api/admin/fcw/{final_id}/revoke 翻转快照
  （revoked＋is_active=false＋revoked_by/at/reason）＋revoke 事件＋审计；
  未知 404、重复 409、缺 reason 422、角色不足 403；
- b（断消费，Q32 哲学）：revoke 后段12 内容生成入口 409（FcwRevoked）。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.models import AuditLog
from app.core.staff_auth.deps import get_auth_session
from app.final.final_whitelist import exit_guard
from app.final.final_whitelist.models import (
    FCW_SNAP_FROZEN,
    FCW_SNAP_REVOKED,
    FCW_SNAP_VERSION_V1,
    FcwFreezeLog,
    FcwSnapshot,
    FinalContentWhitelist,
)
from app.main import app
from app.platform.platform_adaptation.models import GoalFitWeight, PcpTemplate
from app.platform.platform_adaptation.seeds import (
    FIT_WEIGHT_SEEDS,
    PCP_TEMPLATE_SEEDS,
)
from app.product.condition import pwc_rules
from app.product.condition.models import ContentGoal
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import G2Field
from tests.integration.staff_tokens import bearer, issue_staff_token, issue_write_token
from tests.integration.test_fcw_api import (
    COMPLIANCE,
    OPS,
    PLATFORM,
    _assemble_body,
    _freeze,
    _make_ps,
    _seed_static_inputs,
)

REVOKE_PATH = "/api/admin/fcw/{final_id}/revoke"
GENERATE_PATH = "/api/content/generate"


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
    app.dependency_overrides[get_auth_session] = get_test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async with session_factory() as session:
        session.add_all(
            [G2Field(fid="f_a", cat="common", field_name="字段A"),
             G2Field(fid="f_b", cat="selling", field_name="字段B"),
             FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
             FPSourceRoute(route="compliance_risk", name="合规风险面", sort_order=2)]
            + [ContentGoal(code=code) for code in pwc_rules.CONTENT_GOALS]
        )
        for seed in FIT_WEIGHT_SEEDS:
            session.add(GoalFitWeight(goal=seed["goal"], weights=seed["weights"]))
        for tpl in PCP_TEMPLATE_SEEDS:
            session.add(
                PcpTemplate(
                    template_id=tpl["template_id"],
                    code=tpl["code"],
                    name=tpl["name"],
                    weights=tpl["weights"],
                )
            )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


async def _issue(client, session_factory) -> dict:
    """发一条全绿 FCW 成品（材料齐＋CCR 清洗＋七 Guard 全绿），返回 fcw 行视图。"""
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    resp = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _snapshot_of(session_factory, final_id: str) -> FcwSnapshot | None:
    async with session_factory() as session:
        return (
            await session.scalars(
                select(FcwSnapshot).where(FcwSnapshot.final_id == final_id)
            )
        ).first()


async def _log_events(session_factory, final_id: str) -> list[str]:
    async with session_factory() as session:
        return [
            row.event
            for row in (
                await session.scalars(
                    select(FcwFreezeLog).where(FcwFreezeLog.final_id == final_id)
                )
            ).all()
        ]


async def _revoke_audit_count(session_factory) -> int:
    async with session_factory() as session:
        return len(
            (
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == "fcw.revoke")
                )
            ).all()
        )


# ---------- 裁决 a：首版快照（final_id 级，版本恒 v1） ----------


async def test_assemble_creates_frozen_snapshot_log_and_audit(
    client, session_factory
):
    """发证即冻结：assemble 后快照存在（frozen/is_active/v1），freeze 事件与
    fcw.issued 审计齐；preview 零副作用（不落快照）。"""
    ps_id = await _make_ps(session_factory)
    pws = await _freeze(client, ps_id)
    slot_id = await _seed_static_inputs(client, ps_id)
    await client.post(f"/api/pws/{pws['pws_id']}/ccr/run", json={"actor": COMPLIANCE})
    # 预检不产生快照。
    preview = await client.post(
        "/api/fcw/assemble/preview", json=_assemble_body(ps_id, slot_id)
    )
    assert preview.status_code == 200 and preview.json()["guards_passed"] is True
    async with session_factory() as session:
        n_snap = len((await session.scalars(select(FcwSnapshot))).all())
        n_log = len((await session.scalars(select(FcwFreezeLog))).all())
    assert n_snap == 0 and n_log == 0

    issued = await client.post("/api/fcw/assemble", json=_assemble_body(ps_id, slot_id))
    assert issued.status_code == 200, issued.text
    final_id = issued.json()["final_id"]
    snap = await _snapshot_of(session_factory, final_id)
    assert snap is not None
    assert snap.version == FCW_SNAP_VERSION_V1
    assert snap.status == FCW_SNAP_FROZEN
    assert snap.is_active is True
    assert await _log_events(session_factory, final_id) == ["freeze"]


async def test_snapshot_carries_six_way_materials_and_score(client, session_factory):
    """快照 JSON＝发证时 6 路输入 id 引用＋score＋guards 明细（不可变物化）。"""
    fcw = await _issue(client, session_factory)
    snap = await _snapshot_of(session_factory, fcw["final_id"])
    assert snap is not None
    mat = snap.snapshot["materials"]
    assert mat["pws_id"] == fcw["pws_id"]
    assert mat["pwc_id"] == fcw["pwc_id"]
    assert mat["pcp_id"] == fcw["pcp_id"]
    assert mat["csp_package_id"] == fcw["csp_package_id"]
    assert mat["cstp_package_id"] == fcw["cstp_package_id"]
    assert mat["cep_package_id"] == fcw["cep_package_id"]
    assert mat["ccr_report_id"] == fcw["ccr_report_id"]
    assert snap.snapshot["score"] == fcw["score"]
    assert isinstance(snap.snapshot["guards"], list) and len(snap.snapshot["guards"]) >= 7


# ---------- 裁决 d：不可变强制（exit_guard 扩 before_update/delete） ----------


async def test_fcw_row_immutable_on_update_and_delete(session_factory):
    """已发证行 UPDATE/DELETE 一律判红（FcwImmutable），发证即冻结。"""
    ps_id = await _make_ps(session_factory)
    async with session_factory() as session:
        # 夹具直接造一行（需显式 issue_scope，同既有 9 处测试惯例）。
        row = FinalContentWhitelist(
            final_id="immut-1",
            tenant_id="t1",
            product_space_id=ps_id,
            pws_id="pws-x",
            pwc_id="pwc-x",
            pcp_id="pcp-x",
            csp_package_id="csp-x",
            cstp_package_id="cstp-x",
            cep_package_id="cep-x",
            platform=PLATFORM,
            slot_id="slot-x",
            goal="ENGAGEMENT",
            guards={},
            guards_passed=True,
            publish_status="published",
            issued_by="ops-1",
        )
        with exit_guard.issue_scope():
            session.add(row)
            await session.flush()
        await session.commit()

    async with session_factory() as session:
        got = await session.get(FinalContentWhitelist, "immut-1")
        got.score = 99.9
        with pytest.raises(exit_guard.FcwImmutable):
            await session.flush()

    async with session_factory() as session:
        got = await session.get(FinalContentWhitelist, "immut-1")
        await session.delete(got)
        with pytest.raises(exit_guard.FcwImmutable):
            await session.flush()


# ---------- 裁决 b（A 案）：revoke 写口 ----------


async def test_revoke_flips_snapshot_and_logs(client, session_factory):
    """revoke：快照 frozen→revoked、is_active=false、revoked_by/at/reason 落齐，
    revoke 事件与 fcw.revoke 审计齐；原成品行仍在（不可变，非删除）。"""
    fcw = await _issue(client, session_factory)
    before_audit = await _revoke_audit_count(session_factory)
    resp = await client.post(
        REVOKE_PATH.format(final_id=fcw["final_id"]),
        json={"reason": "违规内容需作废", "actor": OPS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == FCW_SNAP_REVOKED
    assert body["is_active"] is False
    assert body["version"] == FCW_SNAP_VERSION_V1
    assert body["revoke_reason"] == "违规内容需作废"
    # 写身份闸（Q242 族）：actor 被已验真令牌覆盖（issue_write_token＝s-writer）。
    assert body["revoked_by"] == "s-writer"

    snap = await _snapshot_of(session_factory, fcw["final_id"])
    assert snap is not None and snap.revoked_at is not None
    assert await _log_events(session_factory, fcw["final_id"]) == ["freeze", "revoke"]
    assert await _revoke_audit_count(session_factory) == before_audit + 1
    # 原成品行保留（不可变语义，不是物理删除）。
    async with session_factory() as session:
        assert await session.get(FinalContentWhitelist, fcw["final_id"]) is not None


async def test_revoke_unknown_final_id_404(client, session_factory):
    resp = await client.post(
        REVOKE_PATH.format(final_id="no-such-final"), json={"reason": "x", "actor": OPS}
    )
    assert resp.status_code == 404, resp.text


async def test_revoke_twice_409(client, session_factory):
    """已 revoked（非 active frozen）再 revoke：409（仅 active frozen 可作废）。"""
    fcw = await _issue(client, session_factory)
    first = await client.post(
        REVOKE_PATH.format(final_id=fcw["final_id"]), json={"reason": "r1", "actor": OPS}
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        REVOKE_PATH.format(final_id=fcw["final_id"]), json={"reason": "r2", "actor": OPS}
    )
    assert second.status_code == 409, second.text


async def test_revoke_requires_reason_422(client, session_factory):
    fcw = await _issue(client, session_factory)
    resp = await client.post(
        REVOKE_PATH.format(final_id=fcw["final_id"]), json={"actor": OPS}
    )
    assert resp.status_code == 422, resp.text


async def test_revoke_requires_operations_role(client, session_factory):
    """写口 RBAC＝Q242 族（require_internal_actor(OPERATIONS)）：非 operations 令牌 403。"""
    fcw = await _issue(client, session_factory)
    secret = await issue_staff_token(client, ["product_reviewer"], staff_id="s-rev")
    client.headers.update(bearer(secret))
    resp = await client.post(
        REVOKE_PATH.format(final_id=fcw["final_id"]), json={"reason": "x", "actor": OPS}
    )
    assert resp.status_code == 403, resp.text


# ---------- 裁决 b：段12 断消费（Q32 哲学） ----------


async def test_revoked_fcw_blocks_content_generation(client, session_factory):
    """revoke 后 /api/content/generate 立即 409（FcwRevoked），作废成品不可再生成。"""
    fcw = await _issue(client, session_factory)
    revoke = await client.post(
        REVOKE_PATH.format(final_id=fcw["final_id"]), json={"reason": "作废", "actor": OPS}
    )
    assert revoke.status_code == 200, revoke.text

    resp = await client.post(
        GENERATE_PATH,
        json={"final_id": fcw["final_id"], "kind": "article", "language": "zh-CN", "actor": OPS},
    )
    assert resp.status_code == 409, resp.text
    assert "not consumable" in resp.text


# ---------- Q321 管理端列表带冻结状态（fcw_view 加法扩展） ----------


async def _admin_list_snapshot(client, final_id: str) -> dict:
    params = [("actor_id", OPS["id"])] + [("roles", r) for r in OPS["roles"]]
    resp = await client.get("/api/admin/fcw", params=params)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    item = next(
        (row for row in body["items"] if row["final_id"] == final_id), None
    )
    assert item is not None, f"final_id {final_id} not in admin list"
    return item


async def test_admin_list_carries_frozen_snapshot_status(client, session_factory):
    """发证即冻结：管理端列表项带 snapshot_status=frozen、无作废字段。"""
    fcw = await _issue(client, session_factory)
    item = await _admin_list_snapshot(client, fcw["final_id"])
    assert item["snapshot_status"] == FCW_SNAP_FROZEN
    assert item["snapshot_revoked_at"] is None
    assert item["revoke_reason"] is None


async def test_admin_list_reflects_revoked_status(client, session_factory):
    """revoke 后列表项 snapshot_status=revoked，revoked_at/reason 回带。"""
    fcw = await _issue(client, session_factory)
    revoke = await client.post(
        REVOKE_PATH.format(final_id=fcw["final_id"]),
        json={"reason": "违规定位需作废", "actor": OPS},
    )
    assert revoke.status_code == 200, revoke.text
    item = await _admin_list_snapshot(client, fcw["final_id"])
    assert item["snapshot_status"] == FCW_SNAP_REVOKED
    assert item["snapshot_revoked_at"] is not None
    assert item["revoke_reason"] == "违规定位需作废"
