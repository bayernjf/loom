"""P1-2：staff 门控开着却没有凭据时，启动必须 fail-fast 并给出引导指令。"""

import pytest

from app.main import _assert_staff_credentials


class _FakeSession:
    """只实现 helper 用到的 scalar()，避免为一条启动断言拉起真库。"""

    def __init__(self, active: int) -> None:
        self._active = active
        self.statements = 0

    async def scalar(self, _statement):
        self.statements += 1
        return self._active


async def test_gate_on_without_active_key_fails_fast():
    session = _FakeSession(0)
    with pytest.raises(RuntimeError) as info:
        await _assert_staff_credentials(session)
    message = str(info.value)
    # 运维必须能照着这条消息完成引导，而不是自己去猜为什么全站 401。
    assert "no active staff access token" in message
    assert "LOOM_STAFF_AUTH_ENABLED=false" in message
    assert "POST /api/admin/staff-keys" in message


async def test_gate_on_with_an_active_key_starts_normally():
    session = _FakeSession(1)
    await _assert_staff_credentials(session)
    assert session.statements == 1
