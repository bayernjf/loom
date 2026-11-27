"""Contract coverage for L-07 DIM-MERGE case-evidence prompt migration (0070)."""

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
    / "0070_case_evidence_dim_merge_v05.py"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "case_evidence_dim_merge_v05_0070", MIGRATION
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["case_evidence_dim_merge_v05_0070"] = module
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_and_appended(mod):
    assert mod.revision == "0070_case_evidence_dim_merge_v05"
    assert mod.down_revision == "0069_dim_merge_compliance_risk_prompt"


def test_v05_template_declares_the_case_evidence_placeholder():
    template = seeds.DIM_MERGE_PROMPT_CASE_EVIDENCE_TEMPLATE
    assert "$case_evidence_entries" in template
    assert "case_evidence:<case_id>" in template
    assert "$compliance_risk_entries" in template
    assert "$category_template_entries" in template
    assert seeds.DIM_MERGE_PROMPT_CASE_EVIDENCE_VERSION == "v0.5"


def test_v04_seed_stays_free_of_the_v05_placeholder():
    assert "$case_evidence_entries" not in seeds.DIM_MERGE_PROMPT_COMPLIANCE_TEMPLATE
    assert "case_evidence:<case_id>" not in seeds.DIM_MERGE_PROMPT_COMPLIANCE_TEMPLATE


def test_v05_variables_append_exactly_one_key():
    assert seeds.DIM_MERGE_PROMPT_CASE_EVIDENCE_VARIABLES == [
        *seeds.DIM_MERGE_PROMPT_COMPLIANCE_VARIABLES,
        "case_evidence_entries",
    ]


def test_v05_id_is_deterministic_uuid5():
    assert seeds.DIM_MERGE_PROMPT_CASE_EVIDENCE_ID == str(
        uuid.uuid5(uuid.NAMESPACE_URL, "loom:skill-prompt:DIM-MERGE:v0.5")
    )
