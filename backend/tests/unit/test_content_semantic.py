"""Q121/Q59 单元测试：ARTICLE-SEMANTIC-CHECK 语义复检输出解析（纯函数，容错归一）。"""

import pytest

from app.content.semantic import parse_semantic_output

# ---------- parse_semantic_output ----------


def test_parse_semantic_output_valid():
    assert parse_semantic_output('{"findings": []}') == ([], None)
    findings, error = parse_semantic_output(
        '{"findings": ['
        '{"code": "absolute_guarantee", "message": "绝对化", "excerpt": "100%"},'
        '{"code": "misleading_ambiguity"}]}'
    )
    assert error is None
    assert findings == [
        {"code": "absolute_guarantee", "message": "绝对化", "excerpt": "100%"},
        {"code": "misleading_ambiguity"},
    ]


def test_parse_semantic_output_invalid_json():
    assert parse_semantic_output("not json") == ([], "invalid_json")


@pytest.mark.parametrize(
    "text,reason",
    [
        ("[1, 2, 3]", "not_object"),
        ('"a string"', "not_object"),
        ("{}", "findings_not_array"),
        ('{"findings": "oops"}', "findings_not_array"),
    ],
)
def test_parse_semantic_output_bad_shape(text, reason):
    assert parse_semantic_output(text) == ([], reason)


def test_parse_semantic_output_drops_invalid_items():
    # 项非对象、缺 code、code 非字符串或空白：逐项跳过，不整体失败。
    text = (
        '{"findings": ['
        '"not-an-object",'
        '{"message": "no code"},'
        '{"code": 42},'
        '{"code": "   "},'
        '{"code": "  unsubstantiated_claim  "}'
        "]}"
    )
    findings, error = parse_semantic_output(text)
    assert error is None
    assert findings == [{"code": "unsubstantiated_claim"}]  # code 去首尾空白


def test_parse_semantic_output_drops_non_string_fields():
    findings, error = parse_semantic_output(
        '{"findings": [{"code": "x", "message": 1, "excerpt": ["y"]}]}'
    )
    assert error is None
    assert findings == [{"code": "x"}]  # 非法类型字段丢弃，code 保留
