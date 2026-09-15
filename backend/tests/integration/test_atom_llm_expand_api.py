"""Q86 集成测试：WF-03 原子批量补池（CONFLICT-PRECHECK chat + ATOM-AFFINITY
embedding）第五站真 LLM 全链路。

形态与 Q82-Q85 同档：operations 显式端点 → 花 token 前预闸（PS/池存在、
gate=approved、Q15 达标停拓仅约束 AI 批次）→ chat 产整批 → embedding 第二次
调用向量化批内文本与同维已存向量 → affinity（Q16）/cluster_id（Q19）本地
确定性计算（模型自报值剥离）→ 整批单候选（atom_batch）经 skill7 同一投递通道
落 pending_review → product_reviewer 裁决后适配器复用 atom.submit_batch
（Q14/Q15/同批去重/line 11189/Q17 词表/line 840/Q18 一项不绕）。
create_all 不跑迁移种子：两个合成模型（chat + embedding）、两条场景路由、
CONFLICT-PRECHECK Prompt 均由本文件 helper 自行插入；业务数据全部合成（16 §4）。
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_session
from app.core.model_registry import drivers, synthetic
from app.core.model_registry.drivers import EmbeddingResult
from app.core.model_registry.models import (
    AIModel,
    AISceneRoute,
    SkillPrompt,
    SkillPromptVersion,
)
from app.core.model_registry.seeds import (
    CONFLICT_PRECHECK_PROMPT_ID,
    CONFLICT_PRECHECK_PROMPT_TEMPLATE,
    CONFLICT_PRECHECK_PROMPT_VARIABLES,
    CONFLICT_PRECHECK_PROMPT_VERSION,
    SCENE_ATOM_AFFINITY,
    SCENE_CONFLICT_PRECHECK,
    SYNTHETIC_EMBEDDING_MODEL_ID,
    SYNTHETIC_MODEL_ID,
)
from app.core.skill7.models import SkillCandidate, SkillRun
from app.main import app
from app.product.atom.models import (
    EMBEDDING_DIM,
    AtomCandidate,
    ProductAtomInstance,
)
from app.product.fieldpool.models import FPSourceRoute
from app.product.product_intake.models import (
    G2Field,
    ProductIntakeApplication,
    ProductSpace,
)

OPS = {"id": "ops-1", "roles": ["operations"]}
PLATFORM_ADMIN = {"id": "pa-1", "roles": ["platform_admin"]}
REVIEWER = {"id": "rev-1", "roles": ["product_reviewer"]}
CUSTOMER = {"id": "cust-1", "roles": ["customer"]}


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
        session.add_all([
            AIModel(
                model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
                provider="synthetic", status="active", capability="chat",
            ),
            AIModel(
                model_id=SYNTHETIC_EMBEDDING_MODEL_ID,
                model_code="synthetic-embedding",
                provider="synthetic", status="active", capability="embedding",
            ),
            AISceneRoute(scene=SCENE_CONFLICT_PRECHECK, model_id=SYNTHETIC_MODEL_ID),
            AISceneRoute(scene=SCENE_ATOM_AFFINITY, model_id=SYNTHETIC_EMBEDDING_MODEL_ID),
            SkillPrompt(
                skill_id=SCENE_CONFLICT_PRECHECK,
                current_version=CONFLICT_PRECHECK_PROMPT_VERSION,
            ),
            SkillPromptVersion(
                version_id=CONFLICT_PRECHECK_PROMPT_ID,
                skill_id=SCENE_CONFLICT_PRECHECK,
                version=CONFLICT_PRECHECK_PROMPT_VERSION,
                template=CONFLICT_PRECHECK_PROMPT_TEMPLATE,
                variables={"vars": CONFLICT_PRECHECK_PROMPT_VARIABLES},
            ),
            G2Field(fid="f_a", cat="common", field_name="字段A"),
            G2Field(fid="f_b", cat="selling", field_name="字段B"),
            FPSourceRoute(route="user_input", name="用户输入", sort_order=1),
            FPSourceRoute(route="compliance_risk", name="合规风险面", sort_order=2),
        ])
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
            profile_snapshot={"f_a": "合成面霜", "f_b": "保湿"},
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


async def _approved_pool(
    client, ps_id, *, target_min=15, target_max=30, sensitive=False
):
    dims = [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)]
    if sensitive:
        dims.append(_dim(4, role="risk_control", source_route="compliance_risk"))
    resp = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools",
        json={
            "dimensions": dims,
            "actor": OPS,
            "target_atom_min": target_min,
            "target_atom_max": target_max,
        },
    )
    assert resp.status_code == 200, resp.text
    pool_id = resp.json()["pool_id"]
    gate = await client.post(
        f"/api/field-pools/{pool_id}/gate",
        json={"decision": "approve", "actor": REVIEWER},
    )
    assert gate.status_code == 200, gate.text
    return (await client.get(f"/api/product-spaces/{ps_id}/field-pools/current")).json()


def _expand_body(**kw):
    body = {"actor": OPS}
    body.update(kw)
    return body


def _item(content, dimension_id, **kw):
    return {"content": content, "dimension_id": dimension_id, **kw}


async def _wordlist(client, word, *, level, action="downgrade", target=None):
    item = {"word": word, "level": level, "action": action}
    if target:
        item["downgrade_target"] = target
    resp = await client.post(
        "/api/admin/compliance-wordlist", json={"item": item, "actor": OPS}
    )
    assert resp.status_code == 200, resp.text
    return resp


def _patch_chat(monkeypatch, out):
    builders = dict(synthetic.BUILDERS)
    builders[SCENE_CONFLICT_PRECHECK] = lambda variables: out
    monkeypatch.setattr(synthetic, "BUILDERS", builders)


def _chat_out(dim_id, contents, *, batch_size=None, **item_kw):
    items = [
        {"content": c, "dimension_id": dim_id, "ai_risk": "low", **item_kw}
        for c in contents
    ]
    return {"batch_size": batch_size if batch_size is not None else len(items), "items": items}


async def _confirm(client, cand_id, actor=REVIEWER):
    return await client.post(
        f"/api/skill-candidates/{cand_id}/decision",
        json={"decision": "confirmed", "actor": actor},
    )


async def _candidates(client, ps_id):
    r = await client.get(f"/api/product-spaces/{ps_id}/atom-candidates")
    assert r.status_code == 200, r.text
    return r.json()


# ---------- happy path：双调用 → 本地 affinity/cluster → Gate → 落批 ----------

async def test_llm_expand_happy_path_persists_vectors_and_local_fields(
    client, session_factory
):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)

    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "llm_auto"
    assert body["model_id"] == SYNTHETIC_MODEL_ID
    assert body["input_tokens"] >= 2 and body["output_tokens"] >= 1
    assert body["candidates"] == [{
        "candidate_id": body["candidates"][0]["candidate_id"],
        "state": "pending_review",
        "target_type": "atom_batch",
    }]
    cand_id = body["candidates"][0]["candidate_id"]

    async with session_factory() as session:
        run = await session.get(SkillRun, body["run_id"])
        assert run.source == "llm_auto"
        assert run.model_id == SYNTHETIC_MODEL_ID
        assert run.input_payload["chat_scene"] == SCENE_CONFLICT_PRECHECK
        assert run.input_payload["embedding_scene"] == SCENE_ATOM_AFFINITY
        assert run.input_payload["embedding_model_id"] == SYNTHETIC_EMBEDDING_MODEL_ID
        assert run.input_payload["approved_embedding_count"] == 0
        assert run.input_payload["batch_size"] == 50  # 非敏感 Q14 默认
        # run.output_payload 不带机读键；affinity/cluster 已本地写回。
        assert set(run.output_payload) == {"batch_size", "items"}
        assert run.output_payload["batch_size"] == 50
        out_items = run.output_payload["items"]
        assert len(out_items) == 6
        for it in out_items:
            assert set(it) == {"content", "dimension_id", "ai_risk", "affinity", "cluster_id"}
            assert it["affinity"] is None  # 无同维向量基 → None，不伪造 0

        cand = await session.get(SkillCandidate, cand_id)
        assert cand.state == "pending_review"
        assert "_embeddings" not in run.output_payload
        embeddings = cand.payload["_embeddings"]
        assert len(embeddings) == 6
        assert all(len(v) == EMBEDDING_DIM for v in embeddings.values())

    # operations 不能裁 WF-03 插槽；product_reviewer 可以。
    forb = await _confirm(client, cand_id, actor=OPS)
    assert forb.status_code == 403
    ok = await _confirm(client, cand_id)
    assert ok.status_code == 200, ok.text
    assert ok.json()["state"] == "applied"

    rows = await _candidates(client, ps_id)
    assert len(rows) == 6
    by_dim: dict[str, list] = {}
    for row in rows:
        by_dim.setdefault(row["dimension_id"], []).append(row)
        assert row["affinity"] is None and row["low_affinity"] is False
        assert row["status"] == "pending_evidence"  # 无 evidence，Q18/line 840
    for pair in by_dim.values():
        assert len(pair) == 2
        assert pair[0]["cluster_id"] is not None
        assert pair[0]["cluster_id"] == pair[1]["cluster_id"]

    async with session_factory() as session:
        stored = (
            await session.scalars(
                select(AtomCandidate).where(AtomCandidate.product_space_id == ps_id)
            )
        ).all()
        assert len(stored) == 6
        assert all(row.embedding is not None and len(row.embedding) == EMBEDDING_DIM
                   for row in stored)
    # 未裁前不花第二趟：池里 approved 原子仍为 0。
    assert len(pool["dimensions"]) == 3


async def test_llm_expand_approve_copies_embedding_then_second_run_computes_affinity(
    client, session_factory, monkeypatch
):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]

    # 共享 40 字 CJK 长前缀（仅末字不同）→ 字袋向量余弦过 0.9 成簇线。
    shared = (
        "这是用于字段原子池扩充的合成冲突预检确定性结构候选条目内容示例文本共享前缀段"
    )
    c1, c2 = shared + "甲", shared + "乙"
    _patch_chat(
        monkeypatch,
        _chat_out(d1, [c1, c2], batch_size=2, evidence="合成评论依据"),
    )
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand",
        json=_expand_body(batch_size=2),
    )
    assert r.status_code == 201, r.text
    cand_id = r.json()["candidates"][0]["candidate_id"]
    assert (await _confirm(client, cand_id)).status_code == 200

    rows = await _candidates(client, ps_id)
    assert len(rows) == 2
    assert {row["cluster_id"] for row in rows} == {rows[0]["cluster_id"]}
    assert rows[0]["cluster_id"] is not None
    for row in rows:
        assert row["status"] == "pending_review" and row["conflicts"] == []
        ap = await client.post(
            f"/api/atom-candidates/{row['candidate_id']}/approve",
            json={"actor": REVIEWER},
        )
        assert ap.status_code == 200, ap.text

    atoms = (await client.get(f"/api/product-spaces/{ps_id}/atoms")).json()
    assert len(atoms) == 2

    async with session_factory() as session:
        cand_vec = {}
        for row in rows:
            c = await session.get(AtomCandidate, row["candidate_id"])
            cand_vec[row["content"]] = c.embedding
        inst = list(
            (
                await session.scalars(
                    select(ProductAtomInstance).where(
                        ProductAtomInstance.product_space_id == ps_id
                    )
                )
            ).all()
        )
        assert len(inst) == 2
        by_content = {a.content: a for a in inst}
        assert c1 in by_content and c2 in by_content
        for content, vec in cand_vec.items():
            assert list(by_content[content].embedding) == list(vec)

    # 第二趟：同维新文本 → affinity 基于已存向量本地算出（非 None）。
    c3 = shared[:14] + "新增的确定性补池候选条目内容丙"
    _patch_chat(
        monkeypatch,
        _chat_out(d1, [c3], batch_size=1, evidence="合成评论依据二"),
    )
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand",
        json=_expand_body(batch_size=1),
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]
    async with session_factory() as session:
        run = await session.get(SkillRun, run_id)
        assert run.input_payload["approved_atom_count"] == 2
        assert run.input_payload["approved_embedding_count"] == 2
        item = run.output_payload["items"][0]
        assert item["affinity"] is not None and item["affinity"] > 0.5
        assert item["cluster_id"] is None  # 批内仅一条，不成簇
    cand_id2 = r.json()["candidates"][0]["candidate_id"]
    assert (await _confirm(client, cand_id2)).status_code == 200
    second = await _candidates(client, ps_id)
    new_row = next(row for row in second if row["content"] == c3)
    assert new_row["affinity"] is not None and new_row["low_affinity"] is False


async def test_pre_q86_approved_atom_without_embedding_gives_none_affinity(
    client, session_factory, monkeypatch
):
    # Q86 之前落库的 approved 原子 embedding 为 NULL：不作为 affinity 基，
    # 不伪造 0；approved_embedding_count 只计有向量者。
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    manual = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches",
        json={"items": [_item("历史已通过原子内容", d1, evidence="旧依据")], "actor": OPS},
    )
    assert manual.status_code == 200, manual.text
    cid = manual.json()["candidates"][0]["candidate_id"]
    assert (
        await client.post(
            f"/api/atom-candidates/{cid}/approve", json={"actor": REVIEWER}
        )
    ).status_code == 200

    _patch_chat(
        monkeypatch,
        _chat_out(d1, ["新补池候选条目内容丁"], batch_size=1, evidence="新依据"),
    )
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand",
        json=_expand_body(batch_size=1),
    )
    assert r.status_code == 201, r.text
    async with session_factory() as session:
        run = await session.get(SkillRun, r.json()["run_id"])
        assert run.input_payload["approved_atom_count"] == 1
        assert run.input_payload["approved_embedding_count"] == 0
        assert run.output_payload["items"][0]["affinity"] is None


# ---------- 模型自报 affinity/cluster/评分一律剥离 ----------

async def test_model_supplied_affinity_cluster_and_scores_are_stripped(
    client, session_factory, monkeypatch
):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    shared = "剥离测试共享长前缀用于成簇判定这是合成冲突预检确定性结构候选条目文本"
    out = {
        "batch_size": 2,
        "items": [
            {
                "content": shared + "甲", "dimension_id": d1, "ai_risk": "low",
                "affinity": 0.123, "cluster_id": "fake-cluster", "score": 0.5,
            },
            {
                "content": shared + "乙", "dimension_id": d1, "ai_risk": "low",
                "affinity": 0.999, "cluster_id": "fake-cluster", "score": 0.7,
            },
        ],
    }
    _patch_chat(monkeypatch, out)
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand",
        json=_expand_body(batch_size=2),
    )
    assert r.status_code == 201, r.text
    async with session_factory() as session:
        run = await session.get(SkillRun, r.json()["run_id"])
        for it in run.output_payload["items"]:
            assert set(it) == {"content", "dimension_id", "ai_risk", "affinity", "cluster_id"}
            assert it["affinity"] is None
            assert it["cluster_id"] != "fake-cluster"
        assert run.output_payload["items"][0]["cluster_id"] == \
            run.output_payload["items"][1]["cluster_id"]


# ---------- ai_risk 枚举校验后透传；词表强制只升不降（Q17） ----------

async def test_ai_risk_passthrough_and_wordlist_forces_override(
    client, session_factory, monkeypatch
):
    await _wordlist(client, "强制管控词", level="high", target="低替代表述")
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    out = {
        "batch_size": 2,
        "items": [
            {
                "content": "本品含强制管控词成分需人工单审",
                "dimension_id": d1, "ai_risk": "low", "evidence": "合成依据一",
            },
            {
                "content": "普通保湿表达候选条目内容",
                "dimension_id": d1, "ai_risk": "medium", "evidence": "合成依据二",
            },
        ],
    }
    _patch_chat(monkeypatch, out)
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand",
        json=_expand_body(batch_size=2),
    )
    assert r.status_code == 201, r.text
    cand_id = r.json()["candidates"][0]["candidate_id"]
    assert (await _confirm(client, cand_id)).status_code == 200

    rows = {row["content"]: row for row in await _candidates(client, ps_id)}
    forced = rows["本品含强制管控词成分需人工单审"]
    assert forced["risk_level"] == "high"
    assert forced["risk_source"] == "wordlist"
    matched = [
        m["word"] if isinstance(m, dict) else m for m in (forced["matched_words"] or [])
    ]
    assert "强制管控词" in matched
    conflict_types = {c["type"] for c in forced["conflicts"]}
    assert "high_risk_single_review" in conflict_types
    assert "evidence_required" not in conflict_types  # 已带 evidence
    passthrough = rows["普通保湿表达候选条目内容"]
    assert passthrough["risk_level"] == "medium"
    assert passthrough["risk_source"] == "ai"


# ---------- RBAC 与花 token 前预闸 ----------

async def test_rbac_and_pre_gates(client, session_factory):
    ps_id = await _make_ps(session_factory)
    for actor in (REVIEWER, CUSTOMER):
        r = await client.post(
            f"/api/product-spaces/{ps_id}/atom-batches/llm-expand",
            json=_expand_body(actor=actor),
        )
        assert r.status_code == 403

    r = await client.post(
        "/api/product-spaces/no-such-ps/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 404

    # 有 PS 无池 → 404（与手动批次同口径）。
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 404

    # pending_gate 池 → 409，不调模型。
    plan = await client.post(
        f"/api/product-spaces/{ps_id}/field-pools",
        json={"dimensions": [_dim(1, fid="f_a"), _dim(2, fid="f_b"), _dim(3)],
              "actor": OPS},
    )
    assert plan.status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 409

    # Q15：approved 原子数达 target_atom_max → AI 拓展 409。
    ps2 = await _make_ps(session_factory)
    pool2 = await _approved_pool(client, ps2, target_min=1, target_max=1)
    d1 = pool2["dimensions"][0]["dimension_id"]
    manual = await client.post(
        f"/api/product-spaces/{ps2}/atom-batches",
        json={"items": [_item("达标原子内容", d1, evidence="e")], "actor": OPS},
    )
    cid = manual.json()["candidates"][0]["candidate_id"]
    assert (
        await client.post(
            f"/api/atom-candidates/{cid}/approve", json={"actor": REVIEWER}
        )
    ).status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps2}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 409


# ---------- 结构脏数据：投递前 502（不进 skill7、不花 embedding token） ----------

async def test_structural_dirt_returns_502(client, session_factory, monkeypatch):
    ps_id = await _make_ps(session_factory)
    pool = await _approved_pool(client, ps_id)
    d1 = pool["dimensions"][0]["dimension_id"]
    other_dim = "not-a-selected-dimension"

    def out(items, size=2):
        return {"batch_size": size, "items": items}

    cases = [
        out([_item("甲内容", d1)], size=3),  # 回显漂移
        [],  # 空批次
        out([_item(f"内容{i}", d1) for i in range(3)], size=2),  # 超 batch_size
        out([_item("   ", d1)]),  # 空白 content
        out([_item("坏维度内容", other_dim)]),  # 非 selected 维度
        out([_item("坏事实类型", d1, fact_type="made_up")]),  # 越界 fact_type
        out([_item("坏风险档", d1, ai_risk="severe")]),  # 越界 ai_risk
        out([_item("同一条表达", d1), _item(" 同一条表达 ", d1)]),  # 规范化重复
    ]
    for bad in cases:
        _patch_chat(monkeypatch, bad)
        r = await client.post(
            f"/api/product-spaces/{ps_id}/atom-batches/llm-expand",
            json=_expand_body(batch_size=2),
        )
        assert r.status_code == 502, r.text

    # 全部失败不留 run / 候选。
    async with session_factory() as session:
        run_count = len((await session.scalars(select(SkillRun))).all())
        cand_count = len((await session.scalars(select(SkillCandidate))).all())
    assert run_count == 0 and cand_count == 0


# ---------- 两次调用的预算/能力/Key 语义（沿用 Q82-Q85） ----------

async def test_chat_model_disabled_fallback_and_remote_key(client, session_factory):
    ps_id = await _make_ps(session_factory)
    await _approved_pool(client, ps_id)

    r = await client.patch(
        f"/api/admin/ai-models/{SYNTHETIC_MODEL_ID}",
        json={"status": "disabled", "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 409  # chat 停用且无 fallback，不静默切供应商

    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-backup", "provider": "synthetic",
        "capability": "chat", "actor": PLATFORM_ADMIN,
    })
    backup_id = r.json()["model_id"]
    r = await client.patch(
        f"/api/admin/ai-models/{SYNTHETIC_MODEL_ID}",
        json={"fallback_model_id": backup_id, "actor": PLATFORM_ADMIN},
    )
    assert r.status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 201 and r.json()["model_id"] == backup_id

    # 恢复 chat 路由模型后，远程 chat 模型无 Key → 422。
    r = await client.put(f"/api/admin/ai-scene-routes/{SCENE_CONFLICT_PRECHECK}", json={
        "model_id": (
            await client.post("/api/admin/ai-models", json={
                "model_code": "gpt-nokey", "provider": "openai",
                "capability": "chat", "actor": PLATFORM_ADMIN,
            })
        ).json()["model_id"],
        "actor": OPS,
    })
    assert r.status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 422


async def test_embedding_call_budget_capability_and_key(client, session_factory):
    ps_id = await _make_ps(session_factory)
    await _approved_pool(client, ps_id)

    async def _route_affinity(model_id):
        return await client.put(
            f"/api/admin/ai-scene-routes/{SCENE_ATOM_AFFINITY}",
            json={"model_id": model_id, "actor": OPS},
        )

    # embedding 模型当日预算为 0：chat 已成功，embedding 硬停 409，不留 run。
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "synthetic-embed-zero", "provider": "synthetic",
        "capability": "embedding", "daily_budget": 0, "actor": PLATFORM_ADMIN,
    })
    zero_id = r.json()["model_id"]
    assert (await _route_affinity(zero_id)).status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 409
    async with session_factory() as session:
        assert len((await session.scalars(select(SkillRun))).all()) == 0

    # chat 模型挂到 embedding 场景 → 能力不符 422，不发调用。
    assert (await _route_affinity(SYNTHETIC_MODEL_ID)).status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 422

    # 远程 embedding 模型无 Key → 422。
    r = await client.post("/api/admin/ai-models", json={
        "model_code": "embed-nokey", "provider": "openai",
        "capability": "embedding", "actor": PLATFORM_ADMIN,
    })
    assert (await _route_affinity(r.json()["model_id"])).status_code == 200
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 422


async def test_embedding_row_count_mismatch_is_502(
    client, session_factory, monkeypatch
):
    ps_id = await _make_ps(session_factory)
    await _approved_pool(client, ps_id)

    async def _broken(self, **kwargs):
        return EmbeddingResult(vectors=[], input_tokens=1)

    monkeypatch.setattr(drivers.SyntheticDriver, "embed", _broken)
    r = await client.post(
        f"/api/product-spaces/{ps_id}/atom-batches/llm-expand", json=_expand_body()
    )
    assert r.status_code == 502
    async with session_factory() as session:
        assert len((await session.scalars(select(SkillRun))).all()) == 0
