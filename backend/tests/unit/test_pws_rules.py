"""段6 PWS 纯逻辑单测：就绪门、版本号、重冻三档、查重指纹。"""

import pytest

from app.core.config_center.cache import config_cache
from app.product.whitelist_center import pws_rules as r


def test_readiness_all_green_and_order():
    checks = {
        "approved_field_pool": True,
        "enough_approved_atoms": True,
        "active_pwc": True,
        "no_unresolved_blocked_conflict": True,
        "no_pending_gate_fields": True,
    }
    assert r.all_green(checks) is True
    checks["active_pwc"] = False
    assert r.all_green(checks) is False


def test_next_version_major_increment():
    assert r.next_version([]) == "v1.0"
    assert r.next_version(["v1.0"]) == "v2.0"
    assert r.next_version(["v1.0", "v2.0", "v9.0"]) == "v10.0"
    # 非本形态版本号不影响计数
    assert r.next_version(["v1.0", "draft"]) == "v2.0"


def test_refreeze_tier_mapping():
    assert r.refreeze_tier("atom_compliance_suspend") == r.REFREEZE_FORCED
    assert r.refreeze_tier("wordlist_hit") == r.REFREEZE_FORCED
    assert r.refreeze_tier("asset_increment") == r.REFREEZE_SUGGESTED
    assert r.refreeze_tier("unrelated_change") == r.REFREEZE_NONE
    with pytest.raises(ValueError):
        r.refreeze_tier("nope")


def test_refreeze_tier_uses_config_knob_when_seeded():
    """Q29 配置化（Q361）：映射整体可热更于配置中心 pws.refreeze_tier_map。

    配置与代码默认不一致时以配置为准；配置缺失回落代码默认；配置写入非法
    档位由消费侧防御（不静默放行）。
    """
    try:
        config_cache.apply(
            {
                "pws.refreeze_tier_map": {
                    # 运营把「强制」档的合规暂停调成「建议」档
                    "atom_compliance_suspend": "suggested",
                    # 运营把普通增量调成「免」
                    "asset_increment": "none",
                }
            }
        )
        assert r.refreeze_tier("atom_compliance_suspend") == r.REFREEZE_SUGGESTED
        assert r.refreeze_tier("asset_increment") == r.REFREEZE_NONE
        # 配置映射未覆盖的原因码＝未知原因，仍不放行
        with pytest.raises(ValueError):
            r.refreeze_tier("wordlist_hit")

        # 配置写入非法档位 → 消费侧防御，不静默放行
        config_cache.apply({"pws.refreeze_tier_map": {"unrelated_change": "banana"}})
        with pytest.raises(ValueError):
            r.refreeze_tier("unrelated_change")
    finally:
        config_cache.invalidate()
    # 清空后回落代码默认（seeds 播种值＝本模块常量，单一事实源对账）
    assert r.refreeze_tier("atom_compliance_suspend") == r.REFREEZE_FORCED
    assert r.refreeze_tier("unrelated_change") == r.REFREEZE_NONE


def test_fingerprint_order_insensitive_and_distinct():
    fp1 = r.snapshot_fingerprint(["a1", "a2"], ["p1"])
    fp2 = r.snapshot_fingerprint(["a2", "a1"], ["p1"])
    assert fp1 == fp2
    assert fp1 != r.snapshot_fingerprint(["a1"], ["p1"])
    assert len(fp1) == 64  # sha256 hex


def test_same_tenant_duplicates_hint_only():
    others = [
        {"fingerprint": "same", "pws_id": "x", "product_space_id": "ps2", "version": "v1.0"},
        {"fingerprint": "other", "pws_id": "y", "product_space_id": "ps3", "version": "v1.0"},
    ]
    hits = r.same_tenant_duplicates("same", others)
    assert [h["pws_id"] for h in hits] == ["x"]
    assert r.same_tenant_duplicates("zzz", others) == []
