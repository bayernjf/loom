"""Contract coverage for L-07 DIM-MERGE category-template prompt migration (0068)."""

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

from app.core.model_registry import seeds

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0068_dim_merge_category_template_prompt.py"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "dim_merge_category_template_prompt_0068", MIGRATION
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["dim_merge_category_template_prompt_0068"] = module
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_and_appended(mod):
    assert mod.revision == "0068_dim_merge_category_template_prompt"
    assert mod.down_revision == "0067_content_goal_ratio_seed"


def test_v03_template_declares_the_category_template_placeholder():
    template = seeds.DIM_MERGE_PROMPT_CATEGORY_TEMPLATE
    assert "$category_template_entries" in template
    assert "category_template:<fid>" in template
    assert seeds.DIM_MERGE_PROMPT_CATEGORY_VERSION == "v0.3"


def test_v01_seed_stays_free_of_the_v03_placeholder():
    assert "$category_template_entries" not in seeds.DIM_MERGE_PROMPT_TEMPLATE
    assert "category_template_entries" not in seeds.DIM_MERGE_PROMPT_VARIABLES


def test_v03_variables_append_exactly_one_key():
    assert seeds.DIM_MERGE_PROMPT_CATEGORY_VARIABLES == [
        *seeds.DIM_MERGE_PROMPT_VARIABLES,
        "category_template_entries",
    ]


def test_v03_id_is_deterministic_uuid5():
    assert seeds.DIM_MERGE_PROMPT_CATEGORY_ID == str(
        uuid.uuid5(uuid.NAMESPACE_URL, "loom:skill-prompt:DIM-MERGE:v0.3")
    )
