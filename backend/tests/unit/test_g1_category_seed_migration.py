"""Contract coverage for the Q230 G1 category seed migration (0042).

The migration itself runs on real PG in CI's migration job (`alembic upgrade
head` → drift check → `downgrade -1` → upgrade). This file pins the halves that
are pure logic so a silent edit to the seeded set — or a rebase that breaks the
revision chain — is caught without a PostgreSQL.

The seed list is not a transcription of any source: the authoritative G1
directory is 原文未给出, and these six names were engineering candidates approved
at the Gate (docs/02 C1.174). Pinning them exactly is the point: changing the
category set is a ruling, not a refactor.
"""

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0042_g1_category_seed.py"
)

# Gate 批准的六个顶层平铺类目（顺序即 `_SEED` 的顺序）。
APPROVED = (
    ("beauty_skincare", "美妆护肤"),
    ("food_beverage", "食品饮料"),
    ("mother_baby", "母婴亲子"),
    ("apparel_bags", "服饰鞋包"),
    ("home_daily", "家居日用"),
    ("health_wellness", "健康保健"),
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("g1_category_seed_0042", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["g1_category_seed_0042"] = module
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_and_appended(mod):
    assert mod.revision == "0042_g1_category_seed"
    assert mod.down_revision == "0041_discard_retention_seed"


def test_seed_matches_the_approved_six_categories(mod):
    assert tuple(mod._SEED) == APPROVED


def test_seed_rows_are_active_flat_top_level(mod):
    rows = mod.seed_rows()
    assert len(rows) == len(APPROVED)
    for row in rows:
        assert row["parent_id"] is None  # 平铺顶层，首个真产品未定
        assert row["status"] == "active"  # 段2 CAT-RECOG 只取 active（Q82）
        assert row["merged_into"] is None
        assert row["product_count"] == 0


def test_seed_ids_are_deterministic_and_fit_the_column(mod):
    rows = mod.seed_rows()
    ids = [row["category_id"] for row in rows]
    assert len(set(ids)) == len(ids)  # 无重复主键
    assert all(len(i) <= 36 for i in ids)  # g1_categories.category_id 是 String(36)
    # 稳定 id 契约：重算 uuid5 必须一致（否则重跑/回滚对不上）。
    for (slug, _name), row in zip(APPROVED, rows, strict=True):
        assert row["category_id"] == str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"loom-g1-category-seed:{slug}")
        )