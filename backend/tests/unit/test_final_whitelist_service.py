"""PT-FCW-ASM-V1.0 ``assemble_one`` GuardsFailed 审计 entity_id 回归测试。

修复前 ``entity_id`` 传 ``f"{pws_id}:{slot_id}"``（73 字符），超出
``audit_logs.entity_id`` 的 ``varchar(36)``，GuardsFailed 路径在写审计时抛
``StringDataRightTruncationError``（HTTP 500）。回归锁：``entity_id`` 传单一
``pws_id``（≤36 字符），``slot_id`` 移入 jsonb ``detail``，无信息丢失。
"""

import pytest

from app.core.actor import Actor
from app.final.final_whitelist import fcw_rules, service as svc

PWS_ID = "12345678-1234-1234-1234-123456789012"  # 36 字符
SLOT_ID = "abcdefab-abcd-abcd-abcd-abcdefabcdef"  # 36 字符


class _Pws:
    pws_id = PWS_ID
    tenant_id = "t1"


class _Item:
    ref_id = "pwc-1"


async def test_assemble_blocked_audit_entity_id_is_single_pws(monkeypatch):
    captured = {}

    async def fake_append_audit(session, **kwargs):
        captured.update(kwargs)

    async def fake_prepare(session, **kwargs):
        pws = _Pws()
        item = _Item()
        results = [fcw_rules.GuardResult(code="g2", passed=False, detail={})]
        guard_payload = [{"code": "g2", "passed": False, "detail": {}}]
        score = fcw_rules.ScoreOutcome(score=0.0, incomplete=False, detail={})
        # 12 元组：pws, pwc_item, pcp, csp, cstp, cep, view, materials,
        #          results, guard_payload, score_outcome, slot
        return (pws, item, None, None, None, None, None, None, results, guard_payload, score, None)

    monkeypatch.setattr(svc, "append_audit", fake_append_audit)
    monkeypatch.setattr(svc, "_prepare", fake_prepare)

    actor = Actor(id="ops-1", roles=["operations"])
    with pytest.raises(svc.GuardsFailed):
        await svc.assemble_one(
            None,
            product_space_id="ps-1",
            platform="x",
            goal="ENGAGEMENT",
            slot_id=SLOT_ID,
            actor=actor,
        )

    # entity_id 是单一 pws_id（≤36 字符），不再是超长的复合键。
    assert captured["entity_id"] == PWS_ID
    assert len(captured["entity_id"]) <= 36
    assert captured["entity_type"] == "fcw_assembly"
    # slot_id 移入 jsonb detail，信息不丢。
    assert captured["detail"]["slot_id"] == SLOT_ID
