"""Q119/Q58 多语言交集纯函数单测（不碰 DB，docs/16 单元层）。"""

from app.content.languages import covers_market, eligible_codes

CATALOG = [
    ("zh-CN", []),          # 全市场
    ("en-US", ["US"]),      # 仅美国
    ("en-GB", ["GB", "US"]),
]


def test_covers_market_empty_catalog_covers_all():
    # 空 markets = 全市场，含 country 为空的通用发布位。
    assert covers_market([], None) is True
    assert covers_market([], "US") is True
    assert covers_market(None, "CN") is True


def test_covers_market_scoped():
    assert covers_market(["US"], "US") is True
    assert covers_market(["GB", "US"], "US") is True
    assert covers_market(["US"], "CN") is False
    # 受限语言不覆盖 country 为空的通用发布位。
    assert covers_market(["US"], None) is False


def test_eligible_no_product_constraint_uses_market():
    assert eligible_codes(CATALOG, "US", None) == ["zh-CN", "en-US", "en-GB"]
    assert eligible_codes(CATALOG, "CN", None) == ["zh-CN"]
    assert eligible_codes(CATALOG, None, None) == ["zh-CN"]
    # 空产品目标语言 = 未声明，等同不限制。
    assert eligible_codes(CATALOG, "US", []) == ["zh-CN", "en-US", "en-GB"]


def test_eligible_product_side_narrows():
    # 产品只声明英文（en-US）：交集排除 zh-CN/en-GB。
    assert eligible_codes(CATALOG, "US", ["en-US"]) == ["en-US"]
    # 产品声明的语言不在清单/不覆盖该市场 → 空交集（无可用语言）。
    assert eligible_codes(CATALOG, "US", ["fr-FR"]) == []
    assert eligible_codes(CATALOG, "CN", ["en-US"]) == []


def test_eligible_preserves_catalog_order_and_dedup_not_needed():
    catalog = list(reversed(CATALOG))
    out = eligible_codes(catalog, "US", None)
    assert out == ["en-GB", "en-US", "zh-CN"]
