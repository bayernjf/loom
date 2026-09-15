"""Q82 模型网关纯函数单测：Key 加密、计费 rounding、合成替身构造器。

DB/HTTP 行为见 tests/integration/test_model_gateway_api.py；eval 层不新增
（Q82 不引入确定性纯业务函数，试点行为由后端集成测试覆盖，16 §4）。
"""

from decimal import Decimal

import pytest

from app.core.config import get_settings
from app.core.model_registry import crypto, gateway, synthetic


@pytest.fixture(autouse=True)
def _crypto_key():
    # 每个用例固定主密钥并清空 lru_cache，避免与其他测试的进程态串扰。
    get_settings().master_key = "unit-test-master-key"
    crypto.reset_caches()
    yield
    get_settings().master_key = ""
    crypto.reset_caches()


def test_crypto_roundtrip_and_fingerprint():
    secret = "sk-abcdefgh1234"
    blob = crypto.encrypt(secret)
    assert isinstance(blob, bytes) and secret.encode() not in blob
    assert crypto.decrypt(blob) == secret
    assert crypto.fingerprint(secret) == "1234"
    assert crypto.fingerprint("ab") == "**ab"


def test_crypto_wrong_master_key_fails():
    blob = crypto.encrypt("sk-secret-value")
    get_settings().master_key = "a-different-master-key"
    crypto.reset_caches()
    with pytest.raises(crypto.DecryptionFailed):
        crypto.decrypt(blob)


def test_cost_rounds_half_up_to_six_decimals():
    # 3.333333/1M * 1 token → 0.000003333333 → 0.000003
    assert gateway._cost(Decimal("3.333333"), 1) == Decimal("0.000003")
    # 0.000005 边界按 ROUND_HALF_UP 进位。
    assert gateway._cost(Decimal(5), 1) == Decimal("0.000005")
    assert gateway._cost(Decimal(0), 123456) == Decimal("0.000000")
    assert gateway._cost(Decimal("2.5"), 2_000_000) == Decimal("5.000000")


def test_synthetic_cat_recog_is_deterministic():
    variables = {
        "_profile": {"name": "这是一个超过二十个字长度的产品名称AAAAAA", "brief": "十个字的简介内容哦哦", "sellpoint": ""},
        "_signal_keys": ["name", "brief", "sellpoint"],
        "_category_options": [
            {"category_id": "cat-1", "name": "类目一"},
            {"category_id": "cat-2", "name": "类目二"},
        ],
    }
    out = synthetic.build_cat_recog(variables)
    assert set(out["signals"]) == {"name", "brief", "sellpoint"}
    assert all(0.0 <= v <= 1.0 for v in out["signals"].values())
    assert out["signals"]["name"] > out["signals"]["brief"] > out["signals"]["sellpoint"]
    assert out["candidates"] == [
        {"category_id": "cat-1", "conf": 0.95},
        {"category_id": "cat-2", "conf": 0.80},
    ]
    # 确定性：同输入同输出。
    assert synthetic.build_cat_recog(variables) == out


def test_synthetic_cat_recog_single_option():
    out = synthetic.build_cat_recog(
        {"_profile": {}, "_signal_keys": ["name"], "_category_options": [
            {"category_id": "only", "name": "唯一"}]}
    )
    assert len(out["candidates"]) == 1 and out["candidates"][0]["category_id"] == "only"


def test_synthetic_pwc_builder_is_structural_only():
    # Q83-3：只按维度确定性配对，不造分/不造目的；首维锚点 × 其余各维首原子。
    variables = {"_approved_atoms": [
        {"atom_id": "a1", "dimension_id": "d1"},
        {"atom_id": "a2", "dimension_id": "d2"},
        {"atom_id": "a3", "dimension_id": "d3"},
    ]}
    out = synthetic.build_pwc_builder(variables)
    assert out == {"combos": [
        {"atom_ids": ["a1", "a2"], "goals": []},
        {"atom_ids": ["a1", "a3"], "goals": []},
    ]}
    assert all("logic_score" not in c and "fit_score" not in c for c in out["combos"])
    assert synthetic.build_pwc_builder(variables) == out  # 确定性


def test_synthetic_pwc_builder_caps_at_five_and_requires_two_dimensions():
    variables = {"_approved_atoms": [
        {"atom_id": f"a{i}", "dimension_id": f"d{i}"} for i in range(7)
    ]}
    assert len(synthetic.build_pwc_builder(variables)["combos"]) == 5
    assert synthetic.build_pwc_builder(
        {"_approved_atoms": [{"atom_id": "a1", "dimension_id": "d1"}]}
    ) == {"combos": []}
    assert synthetic.build_pwc_builder({"_approved_atoms": []}) == {"combos": []}


def test_synthetic_type_match_emits_only_coverage_gap_proposals():
    # Q84-3：原样回传类目/必填位；只给未覆盖位造结构提案，不打任何分。
    variables = {
        "_category_id": "cat-1",
        "_required_fids": ["f_name", "m1", "m2"],
        "_active_fids": ["f_name", "f_brief"],
    }
    out = synthetic.build_type_match(variables)
    assert out == {
        "category_id": "cat-1",
        "required_fids": ["f_name", "m1", "m2"],
        "l4_proposals": [
            {"field_name": "待补字段·m1", "definition": "synthetic TYPE-MATCH 覆盖率缺口结构提案"},
            {"field_name": "待补字段·m2", "definition": "synthetic TYPE-MATCH 覆盖率缺口结构提案"},
        ],
    }
    assert all(
        "confidence" not in p and "score" not in p and "fid" not in p
        for p in out["l4_proposals"]
    )
    assert synthetic.build_type_match(variables) == out  # 确定性


def test_synthetic_type_match_full_coverage_gives_empty_proposals():
    out = synthetic.build_type_match({
        "_category_id": "cat-1",
        "_required_fids": ["f_name"],
        "_active_fids": ["f_name"],
    })
    assert out["l4_proposals"] == []
    assert synthetic.build_type_match({"_category_id": "c"}) == {
        "category_id": "c", "required_fids": [], "l4_proposals": [],
    }


def test_synthetic_dim_merge_builds_compliant_plan_and_echoes_targets():
    # Q85：active G2 复用 + 资料键补维度到 3 维；confidence 固定 0.9 结构占位。
    variables = {
        "_routes": [
            {"route": "user_input", "name": "用户输入"},
            {"route": "compliance_risk", "name": "合规风险面"},
        ],
        "_active_fields": [{"fid": "f_a", "field_name": "字段A"}],
        "_profile": {"f_b": "x"},
        "_sensitive": True,
        "_industry_tag": "medical",
        "_dim_min": 3,
        "_dim_max": 8,
        "_target_atom_min": 15,
        "_target_atom_max": 30,
    }
    out = synthetic.build_dim_merge(variables)
    assert out["target_atom_min"] == 15 and out["target_atom_max"] == 30
    dims = out["dimensions"]
    assert 3 <= len(dims) <= 8
    assert {d["role"] for d in dims} == {"product_attribute", "risk_control"}
    risk = [d for d in dims if d["role"] == "risk_control"]
    assert risk[0]["source_route"] == "compliance_risk"
    assert risk[0]["source_ref"] == "industry_tag:medical"
    assert dims[0]["fid"] == "f_a" and dims[0]["source_ref"] == "g2:f_a"
    assert all(d["confidence"] == 0.9 for d in dims)
    assert all(d["source_ref"].strip() for d in dims)  # line 14081 依据红线
    assert synthetic.build_dim_merge(variables) == out  # 确定性


def test_synthetic_dim_merge_non_sensitive_has_no_risk_dimension():
    out = synthetic.build_dim_merge({
        "_routes": [{"route": "user_input", "name": "用户输入"}],
        "_active_fields": [
            {"fid": f"f{i}", "field_name": f"字段{i}"} for i in range(10)
        ],
        "_profile": {},
        "_sensitive": False,
        "_dim_min": 3,
        "_dim_max": 8,
        "_target_atom_min": 15,
        "_target_atom_max": 30,
    })
    assert len(out["dimensions"]) == 8  # 受 dim_max 截断
    assert all(d["role"] == "product_attribute" for d in out["dimensions"])


# ---------- Q86：CONFLICT-PRECHECK 结构替身 + 确定性 embedding ----------

def test_synthetic_conflict_precheck_batch_shape_and_echo():
    out = synthetic.build_conflict_precheck({
        "_batch_size": 3,
        "_selected_dims": [
            {"dimension_id": "d1", "field_name": "容量"},
            {"dimension_id": "d2", "field_name": "成分"},
        ],
    })
    assert out["batch_size"] == 3 and len(out["items"]) == 3
    assert all(set(i) == {"content", "dimension_id", "ai_risk"} for i in out["items"])
    assert all(i["ai_risk"] == "low" for i in out["items"])
    # 不出 affinity/cluster_id/fact_type/evidence（编排侧本地计算/不造事实）。
    pair = [i for i in out["items"] if i["dimension_id"] == "d1"]
    assert len(pair) == 2 and pair[0]["content"] != pair[1]["content"]


def test_synthetic_conflict_precheck_caps_at_batch_size():
    out = synthetic.build_conflict_precheck({
        "_batch_size": 1,
        "_selected_dims": [{"dimension_id": "d1", "field_name": "x"}],
    })
    assert len(out["items"]) == 1


def test_embed_texts_deterministic_dim_and_pair_similarity():
    from app.product.atom import atom_rules
    from app.product.atom.models import EMBEDDING_DIM

    out = synthetic.build_conflict_precheck({
        "_batch_size": 4,
        "_selected_dims": [
            {"dimension_id": "d1", "field_name": "容量毫升"},
            {"dimension_id": "d2", "field_name": "主要成分浓度"},
        ],
    })
    texts = [i["content"] for i in out["items"]]
    vectors = synthetic.embed_texts(texts)
    assert all(len(v) == EMBEDDING_DIM for v in vectors)
    assert vectors[0] == synthetic.embed_texts([texts[0]])[0]  # 同文本同向量
    # 同维近似对 ≥ 0.9 成簇；跨维（即使共享前缀）不连边由 labels 保证。
    assert atom_rules.cosine_similarity(vectors[0], vectors[1]) >= 0.9
