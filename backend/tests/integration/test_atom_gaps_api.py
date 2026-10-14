"""Q360 段4 缺口批 API 集成测试：Q16 排序 / Q18 AI 补证+运营待办 /
Q19 keeper 自动推荐 / Q20 废弃恢复重走审核。

对应 docs/25 §8.1 四行销账；AI 补证走 ATOM-EVIDENCE 场景（synthetic 替身注册，
与 test_content_l10n_api 同款场景注册模式）。
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.model_registry.models import (
    AIModel,
    AISceneRoute,
    SkillPrompt,
    SkillPromptVersion,
)
from app.core.model_registry.seeds import (
    ATOM_EVIDENCE_PROMPT_ID,
    ATOM_EVIDENCE_PROMPT_TEMPLATE,
    ATOM_EVIDENCE_PROMPT_VARIABLES,
    ATOM_EVIDENCE_PROMPT_VERSION,
    SCENE_ATOM_EVIDENCE,
    SYNTHETIC_MODEL_ID,
)
from app.core.staff_auth.deps import get_auth_session
from app.main import app
from app.product.atom import service as atom_service
from app.product.fieldpool.models import FPSourceRoute
from app.product.modeling.models import OpsTodo
from app.product.product_intake.models import (
    G2Field,
    ProductIntakeApplication,
    ProductSpace,
)
from tests.integration.staff_tokens import acting_as, bearer, issue_write_token

REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
OPS = {"id": "ops-1", "roles": ["operations"]}


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
    # Q242：写口在门控关下也自行验真，走的是 get_auth_session 这条缝。
    app.dependency_overrides[get_auth_session] = get_test_session
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
                FPSourceRoute(
                    route="compliance_risk", name="合规风险面", sort_order=2
                ),
                # Q18：ATOM-EVIDENCE 场景注册（synthetic 替身）。
                AIModel(
                    model_id=SYNTHETIC_MODEL_ID,
                    model_code="synthetic-deterministic",
                    provider="synthetic",
                    status="active",
                ),
                AISceneRoute(scene=SCENE_ATOM_EVIDENCE, model_id=SYNTHETIC_MODEL_ID),
                SkillPrompt(
                    skill_id=SCENE_ATOM_EVIDENCE,
                    current_version=ATOM_EVIDENCE_PROMPT_VERSION,
                ),
                SkillPromptVersion(
                    version_id=ATOM_EVIDENCE_PROMPT_ID,
                    skill_id=SCENE_ATOM_EVIDENCE,
                    version=ATOM_EVIDENCE_PROMPT_VERSION,
                    template=ATOM_EVIDENCE_PROMPT_TEMPLATE,
                    variables={"vars": ATOM_EVIDENCE_PROMPT_VARIABLES},
                ),
            ]
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers.update(bearer(await issue_write_token(ac)))
        yield ac


async def _make_ps(session_factory, *, sensitive=False, industry="general", tenant="t1"):
    async with session_factory() as session:
        intake = ProductIntakeApplication(
            tenant_id=tenant, status="stored", profile={"f_a": "x"}
        )
        session.add(intake)
        await session.flush()
        ps = ProductSpace(
            tenant_id=tenant,
            intake_id=intake.intake_id,
            sensitive_industry=sensitive,
            industry_tag=industry,
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


async def _approved_pool(client, ps_id, *, target_min=15, target_max=30):
    dims = [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)]
    body = {
        "dimensions": dims,
        "actor": OPS,
        "target_atom_min": target_min,
        "target_atom_max": target_max,
    }
    resp = await client.post(f"/api/product-spaces/{ps_id}/field-pools", json=body)
    assert resp.status_code == 200, resp.text
    pool_id = resp.json()["pool_id"]
    gate = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text
    pool = await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")
    return pool.json()


def _item(content, dimension_id, **kw):
    return {"content": content, "dimension_id": dimension_id, **kw}


async def _submit_batch(client, ps_id, items, **extra):
    body = {"items": items, "actor": OPS, **extra}
    return await client.post(f"/api/product-spaces/{ps_id}/atom-batches", json=body)


async def _open_evidence_todos(session_factory, candidate_id: str) -> list:
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(OpsTodo).where(
                    OpsTodo.todo_type == "evidence",
                    OpsTodo.entity_type == "atom_candidate",
                    OpsTodo.entity_id == candidate_id,
                )
            )
        ).all()
        return list(rows)


# ---------- Q16 排序 ----------

async def test_candidate_and_atom_sort_by_affinity_q16(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1, d2 = (d["dimension_id"] for d in pool["dimensions"][:2])

    batch = await _submit_batch(
        client,
        ps_id,
        [
            _item("低亲和", d1, evidence="e", affinity=0.2),
            _item("无亲和", d2, evidence="e"),
            _item("高亲和", d1, evidence="e", affinity=0.9),
        ],
    )
    assert batch.status_code == 200
    ids = [c["candidate_id"] for c in batch.json()["candidates"]]

    # affinity 排序：非 None 降序，None 恒最后。
    rows = (
        await client.get(f"/api/product-spaces/{ps_id}/atom-candidates?sort=affinity")
    ).json()
    assert [r["content"] for r in rows] == ["高亲和", "低亲和", "无亲和"]

    # 默认契约不变（created_at 原序），非法值 422。
    default = (await client.get(f"/api/product-spaces/{ps_id}/atom-candidates")).json()
    assert len(default) == 3
    assert (
        await client.get(f"/api/product-spaces/{ps_id}/atom-candidates?sort=foo")
    ).status_code == 422

    # 正式原子列表同支持 affinity 排序：三条都批准后按亲和度降序。
    for cid in ids:
        assert (
            await client.post(f"/api/atom-candidates/{cid}/approve", json={"actor": REVIEWER})
        ).status_code == 200
    atoms = (await client.get(f"/api/product-spaces/{ps_id}/atoms?sort=affinity")).json()
    assert [a["content"] for a in atoms] == ["高亲和", "低亲和", "无亲和"]


# ---------- Q18 运营待办 + AI 补证 ----------

async def test_evidence_todo_auto_open_resolve_and_revive_q18(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1, d2 = (d["dimension_id"] for d in pool["dimensions"][:2])

    batch = await _submit_batch(
        client,
        ps_id,
        [_item("待补证据甲", d1, ai_risk="high"), _item("待补证据乙", d2, ai_risk="high")],
    )
    c_a, c_b = (c["candidate_id"] for c in batch.json()["candidates"])

    # 落 pending_evidence 即自动开 evidence 待办（幂等）。
    todos_a = await _open_evidence_todos(session_factory, c_a)
    assert len(todos_a) == 1
    assert todos_a[0].status == "open"
    assert todos_a[0].assignee_role == "operations"
    assert todos_a[0].due_at is not None

    # 人工补证据 → 待办关闭。
    sup = await client.post(
        f"/api/atom-candidates/{c_a}/evidence", json={"evidence": "人工补的依据", "actor": OPS}
    )
    assert sup.status_code == 200
    todos_a = await _open_evidence_todos(session_factory, c_a)
    assert todos_a[0].resolved_at is not None
    assert todos_a[0].resolution == "evidence_supplied"

    # 超时自动驳回 → 待办以 evidence_timeout 关闭；复活重开新待办。
    async with session_factory() as session:
        count = await atom_service.sweep_evidence_timeouts(
            session, datetime.now(UTC) + timedelta(days=8)
        )
        await session.commit()
    assert count == 1
    todos_b = await _open_evidence_todos(session_factory, c_b)
    assert todos_b[0].resolved_at is not None
    assert todos_b[0].resolution == "evidence_timeout"

    revive = await client.post(f"/api/atom-candidates/{c_b}/revive", json={"actor": OPS})
    assert revive.status_code == 200
    assert revive.json()["status"] == "pending_evidence"
    assert len(await _open_evidence_todos(session_factory, c_b)) == 2  # 1 关 1 开


async def test_ai_supplement_evidence_one_round_q18(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    cid = (
        await _submit_batch(client, ps_id, [_item("待 AI 补证", d1, ai_risk="high")])
    ).json()["candidates"][0]["candidate_id"]

    # 花钱动作：非 operations → 403（换一枚只有 reviewer 的令牌）。
    async with acting_as(client, ["product_reviewer"], staff_id="s-rev"):
        assert (
            await client.post(
                f"/api/atom-candidates/{cid}/evidence/ai-supplement", json={"actor": OPS}
            )
        ).status_code == 403

    resp = await client.post(
        f"/api/atom-candidates/{cid}/evidence/ai-supplement", json={"actor": OPS}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending_review"
    assert "AI 补证" in data["evidence"]
    assert data["evidence_due_at"] is None
    open_types = {c["type"] for c in data["conflicts"] if c["resolved_at"] is None}
    assert open_types == {"high_risk_single_review"}

    # 待办以 evidence_ai_supplied 关闭。
    todos = await _open_evidence_todos(session_factory, cid)
    assert todos[0].resolved_at is not None
    assert todos[0].resolution == "evidence_ai_supplied"

    # 已非 pending_evidence → 409。
    again = await client.post(
        f"/api/atom-candidates/{cid}/evidence/ai-supplement", json={"actor": OPS}
    )
    assert again.status_code == 409


async def test_ai_supplement_invalid_output_502_q18(client, session_factory, monkeypatch):
    from app.core.model_registry.gateway import Invocation

    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1, d2 = (d["dimension_id"] for d in pool["dimensions"][:2])
    batch = await _submit_batch(
        client, ps_id, [_item("补证甲", d1), _item("补证乙", d2)]
    )
    c_bad, c_empty = (c["candidate_id"] for c in batch.json()["candidates"])

    def _fake(text: str):
        async def _invoke(session, scene, variables):
            return Invocation(
                model_id="m-1",
                model_code="synthetic-deterministic",
                provider="synthetic",
                text=text,
                input_tokens=0,
                output_tokens=0,
                input_cost=0,
                output_cost=0,
                currency_code=None,
            )

        return _invoke

    # 非 JSON → 502。
    monkeypatch.setattr(atom_service.gateway, "invoke", _fake("不是 JSON"))
    r = await client.post(
        f"/api/atom-candidates/{c_bad}/evidence/ai-supplement", json={"actor": OPS}
    )
    assert r.status_code == 502
    # 输出空证据 → 502；候选保持 pending_evidence。
    monkeypatch.setattr(atom_service.gateway, "invoke", _fake('{"evidence": ""}'))
    r = await client.post(
        f"/api/atom-candidates/{c_empty}/evidence/ai-supplement", json={"actor": OPS}
    )
    assert r.status_code == 502
    rows = (await client.get(f"/api/product-spaces/{ps_id}/atom-candidates")).json()
    by_id = {r["candidate_id"]: r for r in rows}
    assert by_id[c_empty]["status"] == "pending_evidence"


# ---------- Q19 keeper 自动推荐 ----------

async def test_cluster_members_recommendation_and_default_keeper_q19(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    batch = await _submit_batch(
        client,
        ps_id,
        [
            _item("拍照清晰", d1, evidence="e", affinity=0.9, cluster_id="cl-g1"),
            _item("成像清楚", d1, evidence="e", affinity=0.6, cluster_id="cl-g1"),
            _item("拍摄锐利", d1, evidence="e", cluster_id="cl-g1"),
        ],
    )
    m1, m2, m3 = (c["candidate_id"] for c in batch.json()["candidates"])

    members = (await client.get("/api/atom-clusters/cl-g1/members")).json()
    assert members["recommended_keeper_id"] == m1  # 亲和度最高者
    assert len(members["members"]) == 3

    # 不传 keeper → 用自动推荐预填，其余成员合并为 alias。
    resolved = await client.post("/api/atom-clusters/cl-g1/resolve", json={"actor": REVIEWER})
    assert resolved.status_code == 200
    assert set(resolved.json()["merged"]) == {m2, m3}

    atom = await client.post(f"/api/atom-candidates/{m1}/approve", json={"actor": REVIEWER})
    assert atom.status_code == 200
    assert "成像清楚" in atom.json()["aliases"]
    assert "拍摄锐利" in atom.json()["aliases"]


# ---------- Q20 废弃恢复重走审核 ----------

async def test_atom_restore_reenters_review_q20(client, session_factory):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    cid = (
        await _submit_batch(client, ps_id, [_item("恢复原子", d1, evidence="e")])
    ).json()["candidates"][0]["candidate_id"]
    atom_id = (
        await client.post(f"/api/atom-candidates/{cid}/approve", json={"actor": REVIEWER})
    ).json()["atom_id"]

    # 非 deprecated → 409；非 operations → 403。
    assert (await client.post(f"/api/atoms/{atom_id}/restore", json={"actor": OPS})).status_code == 409
    await client.post(f"/api/atoms/{atom_id}/deprecate", json={"actor": OPS})
    async with acting_as(client, ["product_reviewer"], staff_id="s-rev"):
        assert (
            await client.post(f"/api/atoms/{atom_id}/restore", json={"actor": OPS})
        ).status_code == 403

    # 恢复 = 新建候选重走审核；旧实例保持 deprecated。
    restored = await client.post(f"/api/atoms/{atom_id}/restore", json={"actor": OPS})
    assert restored.status_code == 200
    data = restored.json()
    assert data["status"] == "pending_review"
    assert data["content"] == "恢复原子"
    assert data["candidate_id"] != cid
    atoms = (await client.get(f"/api/product-spaces/{ps_id}/atoms")).json()
    assert next(a for a in atoms if a["atom_id"] == atom_id)["status"] == "deprecated"

    # 新候选走既有 Gate：审核通过派生新的正式实例。
    new_atom = await client.post(
        f"/api/atom-candidates/{data['candidate_id']}/approve", json={"actor": REVIEWER}
    )
    assert new_atom.status_code == 200
    assert new_atom.json()["atom_id"] != atom_id


async def test_atom_restore_fact_uniqueness_q20(client, session_factory):
    """事实原子恢复：排除自身后无其它存活值 → 恢复成功；恢复后值重新被保留。

    注：line 11189 保留语义使"同值在别处存活"在正常流下不可构造（第二次提交
    即 409），故此处验证可达语义——恢复本身不因自身候选/实例误报冲突。
    """
    ps1 = await _make_ps(session_factory, tenant="t1")
    pool1 = await _approved_pool(client, ps1)
    d1 = pool1["dimensions"][0]["dimension_id"]
    c1 = (
        await _submit_batch(
            client, ps1, [_item("10ml", d1, fact_type="capacity", evidence="包装标注")]
        )
    ).json()["candidates"][0]["candidate_id"]
    a1 = (
        await client.post(f"/api/atom-candidates/{c1}/approve", json={"actor": REVIEWER})
    ).json()["atom_id"]
    await client.post(f"/api/atoms/{a1}/deprecate", json={"actor": OPS})

    # 仅自身持有（候选+实例均排除）→ 恢复成功，重走审核。
    restored = await client.post(f"/api/atoms/{a1}/restore", json={"actor": OPS})
    assert restored.status_code == 200
    assert restored.json()["status"] == "pending_review"

    # 恢复后值重新被保留（新候选 live）→ 别处提交同值 409。
    ps2 = await _make_ps(session_factory, tenant="t2")
    pool2 = await _approved_pool(client, ps2)
    d2 = pool2["dimensions"][0]["dimension_id"]
    dup = await _submit_batch(
        client, ps2, [_item("10ml", d2, fact_type="capacity", evidence="包装标注")]
    )
    assert dup.status_code == 409
