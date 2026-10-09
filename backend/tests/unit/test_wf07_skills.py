"""WF-07 AI 选包四 Skill synthetic 构造器与场景注册单测（Q326 场景注册）。"""

from app.core.model_registry.synthetic import (
    BUILDERS,
    build_pt_content_goal_plan,
    build_pt_content_goal_tag,
    build_pt_struct_match,
    build_pt_tone_style,
)
from app.product.condition.pwc_rules import CONTENT_GOALS

# ----- PT-CONTENT-GOAL-PLAN -----

def test_goal_plan_with_profile():
    result = build_pt_content_goal_plan({
        "profile_snapshot": {"brand": "acme"},
    })
    goals = result["goals"]
    assert len(goals) <= 3
    assert [g["goal"] for g in goals][:3] == list(CONTENT_GOALS)[:3]
    assert all(0.0 <= g["confidence"] <= 1.0 for g in goals)
    # 按置信度降序
    confidences = [g["confidence"] for g in goals]
    assert confidences == sorted(confidences, reverse=True)


def test_goal_plan_without_profile_is_empty():
    assert build_pt_content_goal_plan({"profile_snapshot": {}}) == {"goals": []}
    assert build_pt_content_goal_plan({}) == {"goals": []}


def test_goal_plan_empty_dictionary_is_empty():
    # 显式传入空 goal 字典（字典被清空）→ 空候选，不回落到工程种子。
    assert build_pt_content_goal_plan({
        "profile_snapshot": {"brand": "acme"}, "available_goals": [],
    }) == {"goals": []}


def test_goal_plan_custom_dictionary():
    result = build_pt_content_goal_plan({
        "profile_snapshot": {"brand": "acme"},
        "available_goals": ["TRUST", "EDUCATION"],
    })
    assert [g["goal"] for g in result["goals"]] == ["TRUST", "EDUCATION"]


# ----- PT-STRUCT-MATCH -----

def test_struct_match_default_partial_when_constraint_missing():
    result = build_pt_struct_match({"profile_snapshot": {"brand": "acme"}})
    structs = result["structures"]
    assert len(structs) <= 2
    assert all(s["partial"] is True for s in structs)
    assert all(0.0 <= s["confidence"] <= 1.0 for s in structs)


def test_struct_match_constraint_present_not_partial():
    result = build_pt_struct_match({
        "profile_snapshot": {"brand": "acme"},
        "slot": {"chars_max": 800},
    })
    assert all(s["partial"] is False for s in result["structures"])


def test_struct_match_empty_dictionary():
    result = build_pt_struct_match({
        "profile_snapshot": {"brand": "acme"}, "available_struct": [],
    })
    assert result == {"structures": []}


# ----- PT-TONE-STYLE -----

def test_tone_style_with_goal():
    result = build_pt_tone_style({"goal": "ENGAGEMENT"})
    assert set(result.keys()) == {"tone", "style"}
    assert isinstance(result["tone"], str) and isinstance(result["style"], str)


def test_tone_style_missing_goal():
    assert build_pt_tone_style({}) == {"error": "goal_required"}


def test_tone_style_empty_pool():
    assert build_pt_tone_style({
        "goal": "ENGAGEMENT", "available_tone": [],
    }) == {"error": "pool_dictionary_missing"}
    assert build_pt_tone_style({
        "goal": "ENGAGEMENT", "available_style": [],
    }) == {"error": "pool_dictionary_missing"}


# ----- PT-CONTENT-GOAL-TAG -----

def test_goal_tag_confirms_goal():
    result = build_pt_content_goal_tag({
        "body": "已生成的正文内容", "goal": "TRUST",
    })
    assert result == {"goal": "TRUST", "confirmed": True, "confidence": 0.88}


def test_goal_tag_missing_body():
    assert build_pt_content_goal_tag({"goal": "TRUST"}) == {
        "error": "content_required"
    }


def test_goal_tag_goal_not_in_dictionary():
    assert build_pt_content_goal_tag({
        "body": "正文", "goal": "NOT_A_GOAL",
    }) == {"error": "goal_not_in_dictionary"}
    assert build_pt_content_goal_tag({"body": "正文"}) == {
        "error": "goal_not_in_dictionary"
    }


# ----- 注册 -----

def test_wf07_skills_registered_in_builders():
    assert BUILDERS["PT-CONTENT-GOAL-PLAN"] is build_pt_content_goal_plan
    assert BUILDERS["PT-STRUCT-MATCH"] is build_pt_struct_match
    assert BUILDERS["PT-TONE-STYLE"] is build_pt_tone_style
    assert BUILDERS["PT-CONTENT-GOAL-TAG"] is build_pt_content_goal_tag


def test_wf07_skills_in_scene_codes():
    from app.core.model_registry.seeds import all_scene_codes

    codes = all_scene_codes()
    for scene in (
        "PT-CONTENT-GOAL-PLAN", "PT-STRUCT-MATCH",
        "PT-TONE-STYLE", "PT-CONTENT-GOAL-TAG",
    ):
        assert scene in codes
