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
    assert "no active token" in message
    assert "LOOM_STAFF_AUTH_ENABLED=true" in message
    assert "bootstrap_staff_key.py" in message
    assert "Next steps" in message
    # 新引导路径不再要求先关闸；这条旧指令必须从报错里消失，否则运维会照做三次改配置。
    assert "LOOM_STAFF_AUTH_ENABLED=false" not in message


async def test_gate_on_with_an_active_key_starts_normally():
    session = _FakeSession(1)
    await _assert_staff_credentials(session)
    assert session.statements == 1


async def test_startup_wraps_database_failure_with_next_steps(monkeypatch):
    """库不可达/迁移未跑时，报错要点名故障并给出修复顺序，而不是只抛原始异常。"""
    import app.main as main_module

    class _BrokenSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            raise ConnectionError("database is down")

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(main_module, "SessionLocal", _BrokenSessionFactory())
    monkeypatch.setattr(main_module.settings, "staff_auth_enabled", True)

    with pytest.raises(RuntimeError) as info:
        async with main_module.lifespan(main_module.app):
            pass

    message = str(info.value)
    assert "ConnectionError: database is down" in message
    assert "alembic upgrade head" in message
    assert "scripts/bootstrap_staff_key.py" in message
