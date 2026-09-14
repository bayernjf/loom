"""M10c：FastAPI lifespan 启动引导配置缓存（含失败回落策略）。"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import main
from app.core.config_center.cache import config_cache
from app.core.config_center.knobs import knob
from app.core.config_center.models import ConfigItem, ConfigItemVersion
from app.core.config_center.seeds import CONFIG_SEEDS
from app.core.db import Base


@pytest.fixture(autouse=True)
def _reset_cache():
    config_cache.invalidate()
    yield
    config_cache.invalidate()


async def test_lifespan_bootstraps_config_cache_from_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        for key, category, value_type, value, source_ref, validation in CONFIG_SEEDS:
            session.add(
                ConfigItem(
                    key=key,
                    category=category,
                    value=99 if key == "pwc.funnel_batch_limit" else value,
                    value_type=value_type,
                    validation=validation,
                    source_ref=source_ref,
                    version=1,
                )
            )
            session.add(
                ConfigItemVersion(
                    version_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"loom-bootstrap:{key}")),
                    key=key,
                    version=1,
                    value=value,
                    change_note="seed",
                )
            )
        await session.commit()

    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main.settings, "scheduler_enabled", False)

    async with main.app.router.lifespan_context(main.app):
        assert config_cache.loaded is True
        assert knob("pwc.funnel_batch_limit") == 99
        assert knob("pwc.pool_target") == 100

    await engine.dispose()


async def test_lifespan_survives_bootstrap_failure_with_seed_defaults(monkeypatch):
    class BoomSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(main, "SessionLocal", BoomSession)
    monkeypatch.setattr(main.settings, "scheduler_enabled", False)

    # 引导失败不阻断启动；knob 回落种子默认值。
    async with main.app.router.lifespan_context(main.app):
        assert config_cache.loaded is False
        assert knob("pwc.pool_target") == 100
