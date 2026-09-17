from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.main import app
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import (
    G2Field,
    ProductIntakeApplication,
    ProductSpace,
)

REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
OPS = {"id": "ops-1", "roles": ["operations"]}
DICT_ADMIN = {"id": "dict-1", "roles": ["dictionary_admin"]}


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
    async with session_factory() as session:
        session.add_all(
            [
                G2Field(fid="f_a", cat="common", field_name="字段A"),
                G2Field(fid="f_b", cat="selling", field_name="字段B"),
                FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
                FPSourceRoute(route="g2_frequent", name="G2高频", sort_order=2),
                FPSourceRoute(
                    route="compliance_risk", name="合规风险面", sort_order=3
                ),
                FPSourceRoute(route="disabled_route", name="停用路", enabled=False, sort_order=4),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _make_ps(session_factory, *, sensitive=False) -> str:
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id="t1", status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id="t1",
            intake_id=intake.intake_id,
            sensitive_industry=sensitive,
            industry_tag="medical" if sensitive else "general",
            profile_snapshot={"f_a": "x"},
        )
        session.add(ps)
        await session.commit()
        return ps.product_space_id


def _dim(i, **kw):
    base = {
        "field_name": f"维度{i}",
        "role": "product_attribute",
        "source_route": "user_input",
        "confidence": 0.9,
        "source_ref": f"ref-{i}",
    }
    base.update(kw)
    return base


async def _submit(client, ps_id, dims, actor=OPS, **extra):
    body = {"dimensions": dims, "actor": actor, **extra}
    return await client.post(f"/api/product-spaces/{ps_id}/field-pools", json=body)


# ---------- 方案提交 ----------

async def test_compliant_plan_submits_pending_with_candidates(client, session_factory):
    ps_id = await _make_ps(session_factory)
    dims = [
        _dim(1, fid="f_a"),
        _dim(2, fid="f_b", source_route="g2_frequent"),
        _dim(3),  # 新字段 → g2_field_candidates
    ]
    resp = await _submit(client, ps_id, dims)
    assert resp.status_code == 200
    data = resp.json()
    assert data["gate"] == "pending_gate"
    assert data["compliant"] is True
    assert data["violations"] == []
    new_dim = next(d for d in data["dimensions"] if d["field_name"] == "维度3")
    assert new_dim["fid"] is None
    assert new_dim["candidate_id"] is not None

    candidates = await client.get(
        "/api/admin/g2-candidates",
        params=[
            ("status", "pending_gate"),
            ("actor_id", "dict-1"),
            ("roles", "dictionary_admin"),
        ],
    )
    assert candidates.status_code == 200
    assert len(candidates.json()) == 1
    assert candidates.json()[0]["source_layer"] == "wf02_dim_source"


async def test_sensitive_industry_requires_risk_control(client, session_factory):
    ps_id = await _make_ps(session_factory, sensitive=True)
    resp = await _submit(client, ps_id, [_dim(1), _dim(2), _dim(3)])
    assert resp.status_code == 200
    data = resp.json()
    assert data["compliant"] is False
    assert "missing_risk_control" in data["violations"]

    # 非敏感行业同方案合规（Q11）。
    normal_ps = await _make_ps(session_factory, sensitive=False)
    ok = await _submit(client, normal_ps, [_dim(1), _dim(2), _dim(3)])
    assert ok.json()["compliant"] is True


async def test_below_min_non_compliant_and_above_max_top8_backup(client, session_factory):
    ps_id = await _make_ps(session_factory)
    short = await _submit(client, ps_id, [_dim(1), _dim(2)])
    assert "below_min" in short.json()["violations"]

    ps2 = await _make_ps(session_factory)
    ten = [_dim(i, confidence=0.8 + i * 0.01) for i in range(10)]
    resp = await _submit(client, ps2, ten)
    data = resp.json()
    assert len([d for d in data["dimensions"] if d["status"] == "selected"]) == 8
    backup = [d for d in data["dimensions"] if d["status"] == "backup"]
    assert {d["field_name"] for d in backup} == {"维度0", "维度1"}


async def test_unknown_route_missing_evidence_and_illegal_fid(client, session_factory):
    ps_id = await _make_ps(session_factory)
    dims = [
        _dim(1, source_ref=""),
        _dim(2, source_route="disabled_route"),
        _dim(3, fid="ghost"),
    ]
    data = (await _submit(client, ps_id, dims)).json()
    assert set(data["violations"]) == {
        "missing_evidence",
        "unknown_route",
        "illegal_fid",
    }


async def test_needs_detail_and_dup_flags(client, session_factory):
    ps_id = await _make_ps(session_factory)
    dims = [
        _dim(1, confidence=0.9),
        _dim(2, confidence=0.84),
        _dim(3, confidence=0.95, similarity=0.9, related_fid="f_a"),
    ]
    data = (await _submit(client, ps_id, dims)).json()
    flags = {d["field_name"]: (d["needs_detail"], d["dup"]) for d in data["dimensions"]}
    assert flags["维度1"] == (False, False)
    assert flags["维度2"] == (True, False)
    assert flags["维度3"] == (False, True)


# ---------- Gate ----------

async def test_gate_requires_reviewer_and_blocks_non_compliant(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool_id = (await _submit(client, ps_id, [_dim(1), _dim(2)])).json()["pool_id"]

    # 非审核员 403
    resp = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": OPS},
    )
    assert resp.status_code == 403

    # 不达标方案不能批（Q12 转人工）
    resp = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert resp.status_code == 409

    rejected = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "reject", "reason": "dims insufficient", "actor": REVIEWER},
    )
    assert rejected.status_code == 200
    assert rejected.json()["gate"] == "rejected"


async def test_gate_approve_happy_path_then_locked(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool_id = (
        await _submit(
            client,
            ps_id,
            [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3, confidence=0.7)],
        )
    ).json()["pool_id"]
    resp = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert resp.status_code == 200
    assert resp.json()["gate"] == "approved"

    again = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "reject", "actor": REVIEWER},
    )
    assert again.status_code == 409

    # approved 池不允许重提
    resubmit = await _submit(client, ps_id, [_dim(1), _dim(2), _dim(3)])
    assert resubmit.status_code == 409


async def test_restore_backup_dimension_fixes_below_min(client, session_factory):
    ps_id = await _make_ps(session_factory)
    # 提交 10 个：2 个落备选；先驳回再... 实际直接对 pending 池捞回。
    ten = [_dim(i, confidence=0.8 + i * 0.01) for i in range(10)]
    data = (await _submit(client, ps_id, ten)).json()
    pool_id = data["pool_id"]
    backup = next(d for d in data["dimensions"] if d["status"] == "backup")

    resp = await client.post(
        f"/api/field-pools/{pool_id}/dimensions/{backup['dimension_id']}/restore",
        json={"actor": OPS},
    )
    assert resp.status_code == 200
    selected = [d for d in resp.json()["dimensions"] if d["status"] == "selected"]
    assert len(selected) == 8  # 捞回挤掉最低置信，仍为 Top8
    assert backup["field_name"] in {d["field_name"] for d in selected}


async def test_rejected_pool_can_be_resubmitted(client, session_factory):
    ps_id = await _make_ps(session_factory)
    first = await _submit(client, ps_id, [_dim(1), _dim(2)])
    pool_id = first.json()["pool_id"]
    await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "reject", "reason": "redo", "actor": REVIEWER},
    )
    resp = await _submit(client, ps_id, [_dim(1), _dim(2), _dim(3)])
    assert resp.status_code == 200
    assert resp.json()["compliant"] is True
    assert resp.json()["gate"] == "pending_gate"


# ---------- Q13 转正 ----------

async def test_candidate_promotion_requires_dictionary_admin(client, session_factory):
    ps_id = await _make_ps(session_factory)
    data = (await _submit(client, ps_id, [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)])).json()
    candidate_id = next(
        d["candidate_id"] for d in data["dimensions"] if d["field_name"] == "维度3"
    )

    forbidden = await client.post(
        f"/api/admin/g2-candidates/{candidate_id}/promote",
        json={"fid": "f_new", "actor": REVIEWER},
    )
    assert forbidden.status_code == 403

    dup_fid = await client.post(
        f"/api/admin/g2-candidates/{candidate_id}/promote",
        json={"fid": "f_a", "actor": DICT_ADMIN},
    )
    assert dup_fid.status_code == 409

    ok = await client.post(
        f"/api/admin/g2-candidates/{candidate_id}/promote",
        json={"fid": "f_new", "actor": DICT_ADMIN},
    )
    assert ok.status_code == 200
    assert ok.json()["fid"] == "f_new"

    # 池维度回填合法 fid（Q68）。
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    dim = next(d for d in pool.json()["dimensions"] if d["field_name"] == "维度3")
    assert dim["fid"] == "f_new"

    # 重复转正 409
    again = await client.post(
        f"/api/admin/g2-candidates/{candidate_id}/promote",
        json={"fid": "f_new2", "actor": DICT_ADMIN},
    )
    assert again.status_code == 409


# ---------- Q8 路由表 ----------

async def test_source_route_crud_and_in_use_protection(client, session_factory):
    resp = await client.put(
        "/api/admin/fp-source-routes/new_route",
        json={"item": {"route": "new_route", "name": "新来源", "sort_order": 9}, "actor": OPS},
    )
    assert resp.status_code == 200

    ps_id = await _make_ps(session_factory)
    await _submit(client, ps_id, [_dim(1, source_route="new_route"), _dim(2), _dim(3)])
    blocked = await client.request(
        "DELETE",
        "/api/admin/fp-source-routes/new_route",
        json={"actor": OPS},
    )
    assert blocked.status_code == 409

    unused = await client.request(
        "DELETE", "/api/admin/fp-source-routes/g2_frequent", json={"actor": OPS}
    )
    assert unused.status_code == 200


async def test_submit_for_unknown_product_space_404(client):
    resp = await _submit(client, "nonexistent", [_dim(1), _dim(2), _dim(3)])
    assert resp.status_code == 404
