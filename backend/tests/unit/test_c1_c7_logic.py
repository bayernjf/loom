import pytest

from app.product.modeling import c1, c7


def test_enabled_weights_must_sum_exactly_to_one():
    c1.validate_enabled_weights({"name": 0.50, "brief": 0.33, "sellpoint": 0.17})
    with pytest.raises(c1.WeightSumError):
        c1.validate_enabled_weights({"name": 0.5, "brief": 0.3, "sellpoint": 0.1})
    with pytest.raises(c1.WeightSumError):
        c1.validate_enabled_weights({"name": 1.0, "brief": 0.01})


def test_weighted_conf_and_missing_signal():
    weights = {"name": 0.50, "brief": 0.33, "sellpoint": 0.17}
    conf = c1.weighted_conf(
        {"name": 0.9, "brief": 0.8, "sellpoint": 0.7}, weights
    )
    assert conf == round(0.45 + 0.264 + 0.119, 4)
    with pytest.raises(c1.MissingSignalScore):
        c1.weighted_conf({"name": 0.9}, weights)


def test_three_branches_by_conf():
    high = c1.decide_branch(conf=0.91, threshold=0.90)
    assert high.branch == c1.BRANCH_DIRECT_APPROVE

    mid = c1.decide_branch(conf=0.7, threshold=0.85)
    assert mid.branch == c1.BRANCH_OPS_ASSIST

    low = c1.decide_branch(conf=0.5, threshold=0.85)
    assert low.branch == c1.BRANCH_COLD_START


def test_top_gap_contradiction_forces_ops_assist():
    decision = c1.decide_branch(
        conf=0.95,
        threshold=0.90,
        top_candidates=[{"category_id": "a", "conf": 0.95}, {"category_id": "b", "conf": 0.92}],
    )
    assert decision.branch == c1.BRANCH_OPS_ASSIST
    assert decision.top_gap == 0.03

    clear = c1.decide_branch(
        conf=0.95,
        threshold=0.90,
        top_candidates=[{"category_id": "a", "conf": 0.95}, {"category_id": "b", "conf": 0.70}],
    )
    assert clear.branch == c1.BRANCH_DIRECT_APPROVE


def test_boundary_conf_at_floor_and_threshold():
    # Q1：[0.6, 阈值) 为中置信；conf=0.6 不进冷启动。
    assert c1.decide_branch(conf=0.6, threshold=0.85).branch == c1.BRANCH_OPS_ASSIST
    assert c1.decide_branch(conf=0.5999, threshold=0.85).branch == c1.BRANCH_COLD_START
    assert c1.decide_branch(conf=0.85, threshold=0.85).branch == c1.BRANCH_DIRECT_APPROVE


def test_c7_fid_guard_rejects_dash_and_empty():
    c7.validate_fids(["f_name", "f_brief"])
    for bad in [["-"], ["f_name", "-"], ["f_name", ""]]:
        with pytest.raises(c7.IllegalFid):
            c7.validate_fids(bad)


def test_c7_coverage():
    required = ["f1", "f2", "f3", "f4", "f5"]
    assert c7.coverage(required, ["f1", "f2", "f3"]) == 0.6
    assert c7.coverage(required, ["f1", "f2"]) == 0.4  # <0.6 → 降级 Layer4
    assert c7.coverage([], ["x"]) == 1.0


def test_c7_sibling_pick_max_product_count():
    siblings = [
        {"category_id": "a", "product_count": 3, "template_status": "approved"},
        {"category_id": "b", "product_count": 9, "template_status": "approved"},
        {"category_id": "c", "product_count": 99, "template_status": "draft"},
    ]
    assert c7.pick_sibling(siblings)["category_id"] == "b"
    assert c7.pick_sibling([{"template_status": "draft", "product_count": 5}]) is None
