"""Q59 ③④ v0.1 工程甲案单元测试（docs/29）。

纯函数解析 + 用 fake session 覆盖六类命中与 clean 路径；不打真实库。
"""

from types import SimpleNamespace

from app.content.compliance import (
    _expected_struct_parts,
    find_urls,
    run_construction_check,
    run_country_rule_check,
    scan_words,
    split_paragraphs,
)
from app.decision.layer_strategy.models import Package
from app.product.whitelist_center.models import PwsSnapshot


class FakeSession:
    """按 (模型类, id) 取对象的只读 session 替身。"""

    def __init__(self, objects: dict):
        self._objects = objects

    async def get(self, model, ident):
        return self._objects.get((model, ident))


def _content(body="", country=None):
    return SimpleNamespace(body=body, country=country)


def _fcw(cstp="cstp-1", cep="cep-1", pws="pws-1"):
    return SimpleNamespace(cstp_package_id=cstp, cep_package_id=cep, pws_id=pws)


def _session(*, cstp_payload=None, cep_payload=None, atoms=None):
    objs = {}
    if cstp_payload is not None:
        objs[(Package, "cstp-1")] = SimpleNamespace(payload=cstp_payload)
    if cep_payload is not None:
        objs[(Package, "cep-1")] = SimpleNamespace(payload=cep_payload)
    objs[(PwsSnapshot, "pws-1")] = SimpleNamespace(snapshot={"atoms": atoms or []})
    return FakeSession(objs)


# ---------- 纯函数 ----------


def test_split_paragraphs_ignores_blank_lines():
    assert split_paragraphs("钩子\n\n论点\n收尾\n  ") == ["钩子", "论点", "收尾"]
    assert split_paragraphs("") == []


def test_find_urls():
    assert find_urls("看 https://a.example.com/x 和 http://b.cn") == [
        "https://a.example.com/x",
        "http://b.cn",
    ]
    assert find_urls("无链接") == []


def test_scan_words_case_insensitive():
    assert scan_words("加V领取", ("加v", "微信")) == ["加v"]
    assert scan_words("nothing", ("微信",)) == []


def test_expected_struct_parts():
    assert _expected_struct_parts("钩子-论点-收尾") == 3
    assert _expected_struct_parts("钩子/论点") == 2
    assert _expected_struct_parts("三段式") == 1


# ---------- ③ 施工指令核对 ----------


async def test_construction_hits_all_three_rules():
    content = _content(body="保证最好\n只有一层")
    fcw = _fcw()
    session = _session(cstp_payload={"struct": "钩子-论点-收尾"}, atoms=[])
    word_hits = {"downgrades": [{"word": "保证", "entry_id": "e1"}]}

    result = await run_construction_check(session, content, fcw, word_hits)

    codes = [h["code"] for h in result["hits"]]
    assert codes == [
        "downgrade_not_applied",
        "structure_not_applied",
        "unverified_claim",
    ]
    assert result["structure"] == {
        "expected": "钩子-论点-收尾",
        "paragraphs": 2,
        "satisfied": False,
    }
    assert result["claims"] == [{"word": "保证", "matched_in_pws": False}]
    assert result["unchecked"] == ["tone", "perspective", "explicit", "soften"]


async def test_construction_clean_path():
    content = _content(body="保证钩子\n论点\n收尾")
    fcw = _fcw()
    session = _session(
        cstp_payload={"struct": "钩子-论点-收尾"},
        atoms=[{"content": "7 天见效", "aliases": ["保证"]}],
    )

    result = await run_construction_check(session, content, fcw, {"downgrades": []})

    assert result["hits"] == []
    assert result["structure"]["satisfied"] is True
    assert result["claims"] == [{"word": "保证", "matched_in_pws": True}]


async def test_construction_without_struct_skips_structure():
    content = _content(body="单段")
    session = _session(cstp_payload={}, atoms=[])
    result = await run_construction_check(session, content, _fcw(), {})
    assert result["hits"] == []
    assert result["structure"]["satisfied"] is None


# ---------- ④ 国家规则核对 ----------


async def test_country_cn_url_lead_and_cta():
    content = _content(
        body="看 https://x.example.com 加微信咨询", country="CN"
    )
    session = _session(cep_payload={"cta": "hard"})

    result = await run_country_rule_check(session, content, _fcw())

    codes = [h["code"] for h in result["hits"]]
    assert codes == ["outbound_link", "lead_capture_notice"]
    assert result["urls"] == ["https://x.example.com"]
    assert result["lead_words"] == ["微信"]
    assert result["rule_set"] == "CN"


async def test_country_eu_lead_gets_gdpr_notice():
    content = _content(body="邮箱：a@b.com", country="DE")
    session = _session()

    result = await run_country_rule_check(session, content, _fcw())

    assert [h["code"] for h in result["hits"]] == ["lead_capture_notice"]
    assert "GDPR" in result["hits"][0]["notice"]
    assert result["rule_set"] == "EU"


async def test_country_cta_not_found():
    content = _content(body="纯介绍，无动作。", country=None)
    session = _session(cep_payload={"cta": "soft"})

    result = await run_country_rule_check(session, content, _fcw())

    assert [h["code"] for h in result["hits"]] == ["cta_not_found"]
    assert result["rule_set"] == "generic"


async def test_country_generic_no_hits():
    content = _content(body="无链接无留资", country=None)
    result = await run_country_rule_check(_session(), content, _fcw())
    assert result["hits"] == []
    assert "v0.1-engineering" in result["rules_version"]
