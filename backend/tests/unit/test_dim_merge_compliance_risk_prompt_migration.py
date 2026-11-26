"""Contract coverage for L-07 DIM-MERGE compliance-risk prompt migration (0069)."""

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
    / "0069_dim_merge_compliance_risk_prompt.py"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "dim_merge_compliance_risk_prompt_0069", MIGRATION
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["dim_merge_compliance_risk_prompt_0069"] = module
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_and_appended(mod):
    assert mod.revision == "0069_dim_merge_compliance_risk_prompt"
    assert mod.down_revision == "0068_dim_merge_category_template_prompt"


def test_v04_template_declares_the_compliance_placeholder():
    template = seeds.DIM_MERGE_PROMPT_COMPLIANCE_TEMPLATE
    assert "$compliance_risk_entries" in template
    assert "compliance_risk:<entry_id>" in template
    assert "$category_template_entries" in template
    assert seeds.DIM_MERGE_PROMPT_COMPLIANCE_VERSION == "v0.4"


def test_v03_seed_stays_free_of_the_v04_placeholder():
    assert "$compliance_risk_entries" not in seeds.DIM_MERGE_PROMPT_CATEGORY_TEMPLATE
    assert "compliance_risk:<entry_id>" not in seeds.DIM_MERGE_PROMPT_CATEGORY_TEMPLATE


def test_v04_variables_append_exactly_one_key():
    assert seeds.DIM_MERGE_PROMPT_COMPLIANCE_VARIABLES == [
        *seeds.DIM_MERGE_PROMPT_CATEGORY_VARIABLES,
        "compliance_risk_entries",
    ]


def test_v04_id_is_deterministic_uuid5():
    assert seeds.DIM_MERGE_PROMPT_COMPLIANCE_ID == str(
        uuid.uuid5(uuid.NAMESPACE_URL, "loom:skill-prompt:DIM-MERGE:v0.4")
    )
