"""Contract coverage for the Q361 CP-BAN base wordlist seed (0061).

docs/25 §8.1 #15 tracked 「CP-BAN 默认 6 词未种子」; PRD line 126 fixed the
base-layer CP-BAN disable words. This file pins the pure-logic halves: the
six seeded words, the revision chain, and the downgrade fingerprint rule
(a seed row operations has since retuned must survive). The migration itself
is exercised on real PG in the migration job (upgrade head → downgrade -1 →
upgrade).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0061_compliance_wordlist_seed.py"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("compliance_wordlist_seed_0061", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["compliance_wordlist_seed_0061"] = module
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_and_appended(mod):
    assert mod.revision == "0061_compliance_wordlist_seed"
    assert mod.down_revision == "0060_inspiration_entries"


def test_seed_has_exactly_the_six_prd_words(mod):
    # PRD line 126（docs/01 §3 段10）CP-BAN 禁用 6 词，一字不差。
    assert mod._SEED_WORDS == (
        "permanent removal",
        "cure",
        "treat",
        "根治",
        "保证有效",
        "100%",
    )


def test_seed_rows_are_critical_ban_base_active(mod):
    # 全部 critical 级 + ban 处置 + base 底座层（Q50：base 不可配置）+ active。
    source = MIGRATION.read_text(encoding="utf-8")
    assert '"level": "critical"' in source
    assert '"action": "ban"' in source
    assert '"layer": "base"' in source
    assert '"status": "active"' in source


def test_downgrade_checks_fingerprint_before_deleting(mod):
    # Q351 纪律：运营改过 level/action/layer/status 的词条必须整行保留。
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade", 1)[1]
    for needle in (
        "sa.select",
        "wordlist.c.level",
        "wordlist.c.action",
        "wordlist.c.layer",
        "wordlist.c.status",
        "sa.delete",
    ):
        assert needle in downgrade_body, f"downgrade 缺失指纹要素: {needle}"
    # 种子行以列表驱动，禁止按 word 白名单硬删
    assert "for word in _SEED_WORDS" in downgrade_body
