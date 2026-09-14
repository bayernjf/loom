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
