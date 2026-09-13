from app.product.fieldpool import planning
from app.product.fieldpool.planning import DimInput

ROUTES = frozenset(
    {
        "user_input",
        "common_inspiration",
        "product_inspiration",
        "category_template",
        "g2_frequent",
        "compliance_risk",
    }
)
FIDS = frozenset({"f_a", "f_b"})


def _dim(i, role="product_attribute", conf=0.9, route="user_input", **kw):
    return DimInput(
        field_name=f"d{i}",
        role=role,
        source_route=route,
        confidence=conf,
        source_ref=kw.pop("source_ref", f"ref-{i}"),
        **kw,
    )


def test_compliant_plan_passes_non_sensitive():
    dims = [_dim(1), _dim(2, fid="f_a"), _dim(3, route="g2_frequent", fid="f_b")]
    result = planning.evaluate_plan(
        dims, sensitive=False, enabled_routes=ROUTES, active_fids=FIDS
    )
    assert result.compliant is True
    assert len(result.selected) == 3
    assert result.backup == []


def test_risk_control_only_forced_for_sensitive_industry():
    dims = [_dim(1), _dim(2), _dim(3)]
    assert (
        planning.evaluate_plan(
            dims, sensitive=False, enabled_routes=ROUTES, active_fids=FIDS
        ).compliant
        is True
    )
    sensitive = planning.evaluate_plan(
        list(dims), sensitive=True, enabled_routes=ROUTES, active_fids=FIDS
    )
    assert "missing_risk_control" in sensitive.violations

    dims.append(_dim(4, role="risk_control", route="compliance_risk"))
    fixed = planning.evaluate_plan(
        dims, sensitive=True, enabled_routes=ROUTES, active_fids=FIDS
    )
    assert fixed.compliant is True


def test_product_attribute_always_required():
    dims = [
        _dim(1, role="risk_control", route="compliance_risk"),
        _dim(2, role="risk_control", route="compliance_risk"),
        _dim(3, role="risk_control", route="compliance_risk"),
    ]
    result = planning.evaluate_plan(
        dims, sensitive=True, enabled_routes=ROUTES, active_fids=FIDS
    )
    assert "missing_product_attribute" in result.violations


def test_above_eight_keeps_top8_by_confidence_rest_backup():
    dims = [_dim(i, conf=0.8 + i * 0.01) for i in range(10)]
    result = planning.evaluate_plan(
        dims, sensitive=False, enabled_routes=ROUTES, active_fids=FIDS
    )
    assert len(result.selected) == 8
    assert len(result.backup) == 2
    assert [x.dim.field_name for x in result.selected] == [f"d{i}" for i in range(9, 1, -1)]
    assert {x.dim.field_name for x in result.backup} == {"d0", "d1"}
    assert result.compliant is True


def test_below_three_is_non_compliant_no_auto_fill():
    dims = [_dim(1), _dim(2)]
    result = planning.evaluate_plan(
        dims, sensitive=False, enabled_routes=ROUTES, active_fids=FIDS
    )
    assert "below_min" in result.violations
    assert result.compliant is False
    assert len(result.selected) == 2


def test_missing_evidence_unknown_route_and_illegal_fid_flagged():
    dims = [
        _dim(1, source_ref="  "),
        _dim(2, route="made_up_route"),
        _dim(3, fid="ghost_fid"),
    ]
    result = planning.evaluate_plan(
        dims, sensitive=False, enabled_routes=ROUTES, active_fids=FIDS
    )
    assert set(result.violations) == {
        "missing_evidence",
        "unknown_route",
        "illegal_fid",
    }


def test_detail_line_and_dup_flags():
    high = _dim(1, conf=0.9)
    low = _dim(2, conf=0.84)
    near_dup = _dim(3, conf=0.95, similarity=0.92, related_fid="f_a")
    far = _dim(4, conf=0.95, similarity=0.5)
    result = planning.evaluate_plan(
        [high, low, near_dup, far],
        sensitive=False,
        enabled_routes=ROUTES,
        active_fids=FIDS,
    )
    flags = {x.dim.field_name: (x.needs_detail, x.dup) for x in result.selected}
    assert flags["d1"] == (False, False)
    assert flags["d2"] == (True, False)
    assert flags["d3"] == (False, True)
    assert flags["d4"] == (False, False)
