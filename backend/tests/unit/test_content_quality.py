"""Q120/Q57 单元测试：ARTICLE-QC 输出解析、质量分 advisory 判定、重生成上限配置化。"""

import pytest

from app.content import statemachine as sm
from app.content.models import CONTENT_REVIEW
from app.content.quality import parse_qc_output, quality_advisory_for

# ---------- parse_qc_output ----------


def test_parse_qc_output_valid():
    assert parse_qc_output('{"score": 0.92, "issues": []}') == (0.92, [])
    score, issues = parse_qc_output(
        '{"score": 0.62, "issues": [{"code": "x", "message": "y"}]}'
    )
    assert score == 0.62
    assert len(issues) == 1


def test_parse_qc_output_invalid_json():
    score, issues = parse_qc_output("not json")
    assert score is None
    assert issues == [{"qc_error": "invalid_json"}]


@pytest.mark.parametrize(
    "text,reason",
    [
        ("[1, 2, 3]", "not_object"),
        ('"a string"', "not_object"),
        ("{}", "score_not_number"),
        ('{"score": "high"}', "score_not_number"),
        ('{"score": true}', "score_not_number"),
        ('{"score": 1.5}', "score_out_of_range"),
        ('{"score": -0.1}', "score_out_of_range"),
    ],
)
def test_parse_qc_output_bad_score(text, reason):
    score, issues = parse_qc_output(text)
    assert score is None
    assert issues == [{"qc_error": reason}]


def test_parse_qc_output_issues_normalized():
    # issues 缺失或非数组都归一为空数组，score 仍保留。
    score, issues = parse_qc_output('{"score": 0.8}')
    assert score == 0.8 and issues == []
    score, issues = parse_qc_output('{"score": 0.8, "issues": "oops"}')
    assert score == 0.8 and issues == []


def test_parse_qc_output_bounds():
    assert parse_qc_output('{"score": 0}') == (0.0, [])
    assert parse_qc_output('{"score": 1}') == (1.0, [])


# ---------- quality_advisory_for ----------


def test_quality_advisory_for():
    assert quality_advisory_for(0.92, 0.85) is False
    assert quality_advisory_for(0.62, 0.85) is True
    assert quality_advisory_for(0.85, 0.85) is False  # 恰等于阈值不算低分
    assert quality_advisory_for(None, 0.85) is None  # QC 不可用无 advisory


# ---------- Q56 重生成上限配置化 ----------


def test_revise_allowed_uses_configured_limit():
    # 默认常量上限 3。
    assert sm.revise_allowed(CONTENT_REVIEW, 2) is True
    assert sm.revise_allowed(CONTENT_REVIEW, 3) is False
    # 运营把 content.regen_limit 调小为 1：count=1 即不可再改稿。
    assert sm.revise_allowed(CONTENT_REVIEW, 0, limit=1) is True
    assert sm.revise_allowed(CONTENT_REVIEW, 1, limit=1) is False
    # 非 review 态一律不可改稿。
    assert sm.revise_allowed("ready_for_publish", 0, limit=3) is False
