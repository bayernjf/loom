"""段10 ccr_rules 纯逻辑单测：Q50 三层优先序、Q36 同级从严、PT-COMPLIANCE 一票否决、Q49 触发。"""

from app.core.compliance_wordlist.models import ComplianceWordlistEntry
from app.decision.compliance_center import ccr_rules


def _e(word, *, action, level="high", layer="base", country=None, target=None, eid=None):
    return ComplianceWordlistEntry(
        entry_id=eid or f"e-{word}-{layer}",
        word=word,
        level=level,
        action=action,
        downgrade_target=target,
        country=country,
        layer=layer,
    )


def test_clean_when_no_hit():
    out = ccr_rules.evaluate([_e("根治", action="ban", level="critical")], "温和护理")
    assert out["status"] == ccr_rules.REPORT_CLEAN
    assert out["block_required"] is False


def test_ban_hit_sets_block_required():
    out = ccr_rules.evaluate(
        [_e("根治", action="ban", level="critical")], "保证根治痘痘"
    )
    assert out["status"] == ccr_rules.REPORT_BLOCKED
    assert out["block_required"] is True
    assert out["bans"][0]["word"] == "根治"


def test_downgrade_is_only_suggestion():
    out = ccr_rules.evaluate(
        [_e("治愈", action="downgrade", target="感受改善")], "帮助治愈感"
    )
    assert out["status"] == ccr_rules.REPORT_DOWNGRADE_PENDING
    assert out["block_required"] is False
    assert out["downgrades"][0]["downgrade_target"] == "感受改善"


def test_q50_country_layer_beats_base_downgrade():
    entries = [
        _e("焕白", action="downgrade", target="提亮", layer="base"),
        _e("焕白", action="ban", level="critical", layer="country", country="US"),
    ]
    out = ccr_rules.evaluate(entries, "焕白修护精华")
    assert out["status"] == ccr_rules.REPORT_BLOCKED
    assert out["bans"][0]["layer"] == "country"


def test_q36_same_layer_strictest_wins():
    entries = [
        _e("保证", action="downgrade", target="有助于", layer="base"),
        _e("保证", action="ban", level="critical", layer="base"),
    ]
    out = ccr_rules.evaluate(entries, "保证有效")
    assert out["block_required"] is True
    assert len(out["bans"]) == 1
    assert out["bans"][0]["level"] == "critical"


def test_market_filter():
    us = _e("cure", action="ban", layer="country", country="US")
    assert ccr_rules.applicable_to_market(us, "US")
    assert not ccr_rules.applicable_to_market(us, "CN")
    base = _e("cure", action="downgrade", layer="base")
    assert ccr_rules.applicable_to_market(base, "CN")


def test_normalize_layer():
    assert ccr_rules.normalize_layer(None, "US") == "country"
    assert ccr_rules.normalize_layer(None, None) == "base"
    assert ccr_rules.normalize_layer("platform", None) == "platform"
    try:
        ccr_rules.normalize_layer("bogus", None)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown layer must raise")


def test_sensitive_domain_trigger():
    codes = {"medical", "finance"}
    assert (
        ccr_rules.match_sensitive_domain("medical", False, codes) == "medical"
    )
    # 旗标兜底：行业标未登记但产品标了敏感
    assert (
        ccr_rules.match_sensitive_domain("wart_pen", True, codes) == "wart_pen"
    )
    assert ccr_rules.match_sensitive_domain("general", False, codes) is None
