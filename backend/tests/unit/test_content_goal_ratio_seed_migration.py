"""Contract coverage for the Q44 content-goal ratio seed (0067).

Q44 was blocked on「配比健康度栏目的口径与页面归属」; the PRD already gives
the five single-sided bounds at line 1090. This slice seeds them as a soft
prompt only (no hard dispatch). The migration is pure data and must preserve
any operations edit, so the contract pinned here is:

- revision chain is linear after 0066;
- the seed values live in ``condition/seeds.CONTENT_GOAL_RATIO_DEFAULTS`` (single
  source), not re-typed inside the migration;
- upgrade only touches rows whose two bounds are both NULL;
- downgrade only clears the exact two-column fingerprint.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from app.product.condition import seeds

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0067_content_goal_ratio_seed.py"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "content_goal_ratio_seed_0067", MIGRATION
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["content_goal_ratio_seed_0067"] = module
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_and_appended(mod):
    assert mod.revision == "0067_content_goal_ratio_seed"
    assert mod.down_revision == "0066_client_access_tokens"


def test_seed_is_the_single_source_and_matches_prd_line_1090(mod):
    assert mod.CONTENT_GOAL_RATIO_DEFAULTS == seeds.CONTENT_GOAL_RATIO_DEFAULTS
    assert seeds.CONTENT_GOAL_RATIO_DEFAULTS == {
        "ENGAGEMENT": (None, 0.40),
        "CONVERSION": (None, 0.30),
        "EDUCATION": (0.15, None),
        "TRUST": (0.15, None),
        "RETENTION": (0.10, None),
    }


def test_upgrade_preserves_partially_configured_rows(mod):
    source = MIGRATION.read_text(encoding="utf8")
    assert "goals.c.ratio_min.is_(None)" in source
    assert "goals.c.ratio_max.is_(None)" in source
    assert "values(ratio_min=None, ratio_max=None)" in source
    assert "goals.c.ratio_min == ratio_min" in source
    assert "goals.c.ratio_max == ratio_max" in source
