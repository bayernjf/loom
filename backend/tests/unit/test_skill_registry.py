"""runtime/ YAML 注册表加载单测（14 §2.2 / 15 §2，M10 切片 e）。"""

import pytest

from app.core.skill7 import registry


def test_registry_loads_wf04_and_skills():
    skills = registry.all_skills()
    assert {"PWC-BUILDER", "COMBO-VALIDATE", "PWC-SCORING"} <= set(skills)
    assert "WF-04" in registry.all_workflows()
    builder = skills["PWC-BUILDER"]
    # docs/06 §4.1 / docs/15 §2.2 所列 10 个注册表字段逐项存在。
    for key in (
        "skill_id",
        "layer",
        "version",
        "input_output_schema",
        "knowledge_deps",
        "model_tier",
        "thresholds",
        "failure_policy",
        "review_rule",
        "cost_limit",
    ):
        assert key in builder, key


def test_workflow_gate_slot_role():
    assert registry.review_role("WF-04") == "product_reviewer"


def test_unknown_skill_and_workflow():
    with pytest.raises(registry.RegistryError):
        registry.get_skill("DOES-NOT-EXIST")
    with pytest.raises(registry.RegistryError):
        registry.get_workflow("WF-99")
    with pytest.raises(registry.RegistryError):
        registry.review_role("WF-99")
