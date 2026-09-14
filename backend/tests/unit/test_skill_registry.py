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


def test_registry_loads_wf02_and_skills():
    # M10 WF 替换切片 1/3（Q78）：WF-02 + 字段池三 Skill 登记。
    skills = registry.all_skills()
    assert {"FIELDPOOL-PLAN", "DIM-SOURCE", "DIM-MERGE"} <= set(skills)
    assert "WF-02" in registry.all_workflows()
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
        assert key in skills["DIM-MERGE"], key
    # DIM-MERGE 是 WF-02 唯一候选产出步骤，target=field_plan。
    assert registry.candidate_target_for("WF-02", "DIM-MERGE") == "field_plan"
    assert registry.candidate_target_for("WF-02", "DIM-SOURCE") is None
    assert registry.candidate_target_for("WF-04", "PWC-BUILDER") == "pwc_combo"


def test_registry_loads_wf01_and_skills():
    # M10 WF 替换切片 2/3（Q79）：WF-01 + 段2 六 Skill 登记。
    skills = registry.all_skills()
    assert {
        "PARSE",
        "UNDERSTAND",
        "CAT-RECOG",
        "TYPE-MATCH",
        "MISSING-INFO",
        "RISK-TAG",
    } <= set(skills)
    assert "WF-01" in registry.all_workflows()
    for skill_id in ("PARSE", "UNDERSTAND", "CAT-RECOG", "TYPE-MATCH", "MISSING-INFO", "RISK-TAG"):
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
            assert key in skills[skill_id], (skill_id, key)
    # CAT-RECOG 是 WF-01 唯一候选产出步骤，整结果单候选，target=c1_recognition。
    step = registry.producer_step_for("WF-01", "CAT-RECOG")
    assert step["candidate_target"] == "c1_recognition"
    assert step["single_candidate"] is True
    assert registry.producer_step_for("WF-01", "PARSE") is None
    assert registry.candidate_target_for("WF-01", "CAT-RECOG") == "c1_recognition"
    # Q79：field_plan 单候选约束同样由声明驱动。
    assert registry.producer_step_for("WF-02", "DIM-MERGE")["single_candidate"] is True


def test_registry_loads_wf03_and_skills():
    # M10 WF 替换切片 3/3（Q80）：WF-03 + 段4 四 Skill 登记。
    skills = registry.all_skills()
    assert {
        "ATOM-EXPAND",
        "ATOM-CANON",
        "ATOM-AFFINITY",
        "CONFLICT-PRECHECK",
    } <= set(skills)
    assert "WF-03" in registry.all_workflows()
    for skill_id in ("ATOM-EXPAND", "ATOM-CANON", "ATOM-AFFINITY", "CONFLICT-PRECHECK"):
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
            assert key in skills[skill_id], (skill_id, key)
    # 末步 CONFLICT-PRECHECK 是唯一候选产出步骤，整批单候选，target=atom_batch。
    step = registry.producer_step_for("WF-03", "CONFLICT-PRECHECK")
    assert step["candidate_target"] == "atom_batch"
    assert step["single_candidate"] is True
    assert registry.producer_step_for("WF-03", "ATOM-EXPAND") is None
    assert registry.candidate_target_for("WF-03", "CONFLICT-PRECHECK") == "atom_batch"


def test_workflow_gate_slot_role():
    assert registry.review_role("WF-04") == "product_reviewer"
    assert registry.review_role("WF-02") == "product_reviewer"
    assert registry.review_role("WF-01") == "operations"  # Q79-3
    assert registry.review_role("WF-03") == "product_reviewer"  # Q80-2


def test_unknown_skill_and_workflow():
    with pytest.raises(registry.RegistryError):
        registry.get_skill("DOES-NOT-EXIST")
    with pytest.raises(registry.RegistryError):
        registry.get_workflow("WF-99")
    with pytest.raises(registry.RegistryError):
        registry.review_role("WF-99")
