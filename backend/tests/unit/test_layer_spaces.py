"""Q262 单元测试：layerSpaces 通用底座纯逻辑（Q46）。

覆盖：payload 引用匹配（活跃配方判定，工程口径【实现补】）、platform_admin
权限、池状态枚举。DB 相关的校验/影响面 Gate 用例在集成测试
tests/integration/test_layer_spaces_api.py。
"""

import pytest

from app.core.actor import Actor
from app.decision.layer_strategy import service
from app.decision.layer_strategy.models import (
    ITEM_ARCHIVED,
    ITEM_CANDIDATE,
    ITEM_FORMAL,
    ITEM_FROZEN,
    ITEM_WRITABLE_STATUSES,
)

PA = Actor(id="pa-1", roles=["platform_admin"])
OPS = Actor(id="ops-1", roles=["operations"])


def test_payload_mentions_scalar():
    assert service._payload_mentions({"stage": "认知阶段"}, "认知阶段")
    assert not service._payload_mentions({"stage": "理解"}, "认知阶段")


def test_payload_mentions_nested():
    payload = {"struct": {"hook": "原生", "body": ["原生", "其他"]}}
    assert service._payload_mentions(payload, "原生")
    assert not service._payload_mentions(payload, "不存在")


def test_payload_mentions_value_equality_not_key():
    # 只按值全等判定（工程口径【实现补】），键名不算引用。
    assert not service._payload_mentions({"原生": "x"}, "原生")


def test_require_platform_admin_allows_pa():
    service._require_platform_admin(PA)  # 不抛


def test_require_platform_admin_denies_ops():
    with pytest.raises(service.RoleNotAllowed):
        service._require_platform_admin(OPS)


def test_writable_statuses_are_the_three_pools_only():
    assert set(ITEM_WRITABLE_STATUSES) == {ITEM_CANDIDATE, ITEM_FORMAL, ITEM_FROZEN}
    assert ITEM_ARCHIVED not in ITEM_WRITABLE_STATUSES
