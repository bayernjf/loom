"""Contract coverage for the Q361 refreeze tier mapping seed (0062).

docs/25 §3.3 tracked Q29 as 「未配置化：仍是代码常量」; the mapping is now a
json config-center knob ``pws.refreeze_tier_map`` seeded with the code
default as its value. This file pins the pure-logic halves: the knob is the
single source of truth in seeds.py (migration must not re-type it), the
revision chain, and the downgrade double-fingerprint rule (a knob operations
has since retuned must survive). The migration itself is exercised on real
PG in the migration job.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0062_pws_refreeze_tiers_seed.py"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("pws_refreeze_tiers_seed_0062", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["pws_refreeze_tiers_seed_0062"] = module
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_and_appended(mod):
    assert mod.revision == "0062_pws_refreeze_tiers_seed"
    assert mod.down_revision == "0061_compliance_wordlist_seed"


def test_seed_row_is_the_registered_knob(mod):
    # 单一事实源对账：迁移种的必须是 config_center/seeds.py 里那一行，不二次抄写。
    assert mod._SEED[0] == mod._SEED_KEY == "pws.refreeze_tier_map"
    _key, category, value_type, value, source_ref, validation = mod._SEED
    assert (category, value_type) == ("pws", "json")
    assert validation == {}
    assert "Q29" in source_ref
    # 默认映射与代码常量一致：合规/事实变更强制、普通增量建议、无关变更免
    assert value == {
        "atom_compliance_suspend": "forced",
        "atom_deprecated": "forced",
        "wordlist_hit": "forced",
        "product_fact_change": "forced",
        "asset_increment": "suggested",
        "unrelated_change": "none",
    }


def test_downgrade_checks_the_json_fingerprint_before_deleting(mod):
    # Q351 纪律：运营经配置中心改过 value/validation 的定制行必须整行保留。
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade", 1)[1]
    for needle in (
        "sa.select",
        "config_items.c.value",
        "config_items.c.validation",
        "config_versions.c.change_note",
    ):
        assert needle in downgrade_body, f"downgrade 缺失指纹要素: {needle}"
