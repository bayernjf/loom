"""PT-FCW-ASM-V1.0 纯规则单测：7 项 Guard 逐项可败 + Q54 评分口径。"""

import pytest

from app.final.final_whitelist import fcw_rules as r


def _ref(rid="x", *, ps="ps1", tenant="t1", status="active", gate="approved"):
    return r.MaterialRef(rid, ps, tenant, status, gate)


def _gate(
    *,
    block=False,
    cleaning=True,
    law_required=False,
    law_status=None,
    law_passed=False,
    report_id="ccr1",
    report_status="clean",
):
    return r.Gate(
        latest_report_id=report_id,
        report_status=report_status,
        block_required=block,
        cleaning_passed=cleaning,
        law_review_required=law_required,
        law_review_status=law_status,
        law_review_passed=law_passed,
    )


def _materials(**over):
    base = {
        "pws_id": "pws1",
        "pws_status": "frozen",
        "pws_is_active": True,
        "pws_product_space_id": "ps1",
        "pws_tenant_id": "t1",
        "gate": _gate(),
        "pcp": _ref("pcp1"),
        "csp": _ref("csp1"),
        "cstp": _ref("cstp1"),
        "cep": _ref("cep1"),
        "request_product_space_id": "ps1",
    }
    base.update(over)
    return r.Materials(**base)


def _by_code(results):
    return {g.code: g for g in results}


def test_all_seven_guards_pass_on_green_materials():
    results = r.evaluate_guards(_materials())
    assert len(results) == 7
    assert r.guards_passed(results)
    assert set(_by_code(results)) == {
        r.G1, r.G2, r.G3, r.G4, r.G5, r.G6, r.G7
    }


def test_g1_fails_when_pws_not_frozen():
    out = _by_code(r.evaluate_guards(_materials(pws_status="superseded")))
    assert not out[r.G1].passed
    assert not out[r.G7].passed  # ⑦ 同时要求 frozen+active


def test_g2_fails_on_block_required():
    out = _by_code(
        r.evaluate_guards(_materials(gate=_gate(block=True, cleaning=False, report_status="blocked")))
    )
    assert not out[r.G2].passed


def test_g2_fails_without_cleaning_report():
    # 无报告：block_required 默认 False 但 cleaning_passed=False，不得伪装放行【实现补】
    out = _by_code(
        r.evaluate_guards(
            _materials(gate=_gate(report_id=None, report_status=None, cleaning=False))
        )
    )
    assert not out[r.G2].passed


def test_g3_fails_when_any_package_inactive_or_unapproved():
    out = _by_code(
        r.evaluate_guards(_materials(csp=_ref("csp1", status="archived")))
    )
    assert not out[r.G3].passed
    out = _by_code(
        r.evaluate_guards(_materials(cep=_ref("cep1", gate="pending_gate")))
    )
    assert not out[r.G3].passed
    out = _by_code(
        r.evaluate_guards(_materials(pcp=_ref("pcp1", status="archived")))
    )
    assert not out[r.G3].passed


def test_g4_fails_on_cross_product_space_config():
    out = _by_code(
        r.evaluate_guards(_materials(pcp=_ref("pcp1", ps="ps-other")))
    )
    assert not out[r.G4].passed
    assert _by_code(r.evaluate_guards(_materials()))[r.G4].passed


def test_g5_fails_on_tenant_mismatch():
    out = _by_code(
        r.evaluate_guards(_materials(cstp=_ref("cstp1", tenant="t-other")))
    )
    assert not out[r.G5].passed


def test_g6_law_review_only_blocks_when_required_and_not_approved():
    no_law = _by_code(r.evaluate_guards(_materials()))
    assert no_law[r.G6].passed  # 未触发法审不阻断

    pending = _materials(
        gate=_gate(law_required=True, law_status="pending", law_passed=False)
    )
    assert not _by_code(r.evaluate_guards(pending))[r.G6].passed

    approved = _materials(
        gate=_gate(law_required=True, law_status="approved", law_passed=True)
    )
    assert _by_code(r.evaluate_guards(approved))[r.G6].passed


def test_g7_fails_when_pws_not_active_version():
    out = _by_code(r.evaluate_guards(_materials(pws_is_active=False)))
    assert not out[r.G7].passed


def test_guards_do_not_short_circuit():
    # 多项同败时仍返回全部 7 项（审计完整性）
    results = r.evaluate_guards(
        _materials(
            pws_status="revoked",
            pws_is_active=False,
            gate=_gate(block=True, cleaning=False, report_status="blocked"),
            csp=_ref("csp1", status="archived", ps="ps2", tenant="t2"),
        )
    )
    assert len(results) == 7
    assert not r.guards_passed(results)


def test_q54_score_weights_and_scale():
    # pwc 0.5(×100)×0.4 + fit 80×0.3 + conf 0.8(×100)×0.3 = 20+24+24 = 68
    out = r.score_fcw(
        pwc_score=0.5, slot_fit_score=80.0, package_confs=[0.8, 0.8, 0.8]
    )
    assert out.score == pytest.approx(68.0)
    assert not out.incomplete


def test_q54_score_incomplete_when_any_source_missing():
    out = r.score_fcw(pwc_score=None, slot_fit_score=80.0, package_confs=[0.8, 0.8, 0.8])
    assert out.score is None and out.incomplete and "pwc_score" in out.detail["missing"]

    out = r.score_fcw(pwc_score=0.5, slot_fit_score=None, package_confs=[0.8, None, 0.8])
    assert out.score is None and out.incomplete
    assert set(out.detail["missing"]) == {"slot_fit_score", "package_conf"}
