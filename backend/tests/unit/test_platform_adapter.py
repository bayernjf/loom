"""PLATFORM-ADAPTER 场景 synthetic 构造器与场景注册单测（V1 引擎预备，Q260）。

四态机械映射（PT-PLATFORM-ADAPTER-V1.0）：
- 无 frozen PWS → missing、不造假；
- 命中 effect=blocked → block；effect=partial → downgrade；
- 存在 active 动态信号 → pending_review；其余 → allow；
- AI 输出一律 gate=pending_review。
"""

from app.core.model_registry.synthetic import BUILDERS, build_platform_adapter


def _pws(frozen: bool = True) -> dict:
    return {"product_space_id": "ps-1", "frozen": frozen}


def _hit(effect: str, rule_id: str = "r-1") -> dict:
    return {"effect": effect, "rule_id": rule_id}


def test_no_pws_returns_missing():
    assert build_platform_adapter({}) == {"missing": True, "reason": "no_frozen_pws"}


def test_non_frozen_pws_returns_missing():
    assert build_platform_adapter({"pws": _pws(frozen=False)}) == {
        "missing": True, "reason": "no_frozen_pws"
    }


def test_blocked_rule_gives_block():
    out = build_platform_adapter({"pws": _pws(), "platform_rules": [_hit("blocked")]})
    assert out == {
        "missing": False, "decision": "block",
        "reason": "platform rule effect=blocked", "refs": ["rule:r-1"],
        "gate": "pending_review",
    }


def test_partial_rule_gives_downgrade():
    out = build_platform_adapter({"pws": _pws(), "platform_rules": [_hit("partial")]})
    assert out["decision"] == "downgrade"
    assert out["gate"] == "pending_review"


def test_dynamic_events_give_pending_review():
    out = build_platform_adapter({
        "pws": _pws(),
        "dynamic_events": [{"event_type": "policy-change", "severity": "high"}],
    })
    assert out["decision"] == "pending_review"
    assert out["reason"] == "active dynamic signal requires human review"


def test_no_hits_no_events_gives_allow():
    out = build_platform_adapter({"pws": _pws()})
    assert out["decision"] == "allow"
    assert out["gate"] == "pending_review"


def test_refs_skip_rule_without_rule_id():
    out = build_platform_adapter({"pws": _pws(), "platform_rules": [{"effect": "blocked"}]})
    assert out["refs"] == []


def test_platform_adapter_registered_in_builders():
    assert BUILDERS["PLATFORM-ADAPTER"] is build_platform_adapter


def test_platform_adapter_in_scene_codes():
    from app.core.model_registry.seeds import all_scene_codes

    assert "PLATFORM-ADAPTER" in all_scene_codes()
