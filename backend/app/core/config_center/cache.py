"""进程内配置快照缓存（14 §2.4 热更新：发布即原子切换）。

V1 为模块化单体单进程：发布后在同事务 after_commit 钩子内原子替换快照，
纯逻辑规则模块可用同步 get_* 读最新值，无需穿 DB。
多副本部署的跨进程广播（Redis Streams/pub-sub）随部署形态落地，挂账见 08 M10。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_center.models import ConfigItem


class ConfigCache:
    def __init__(self) -> None:
        self._snapshot: dict[str, object] = {}
        self.loaded = False

    async def reload(self, session: AsyncSession) -> None:
        rows = (await session.scalars(select(ConfigItem))).all()
        self._snapshot = {row.key: row.value for row in rows}
        self.loaded = True

    def apply(self, updates: dict[str, object]) -> None:
        # 单次 dict 更新 = 读侧原子切换（14 §2.4）。
        self._snapshot = {**self._snapshot, **updates}
        self.loaded = True

    def invalidate(self) -> None:
        self._snapshot = {}
        self.loaded = False

    def get(self, key: str, default=None):
        return self._snapshot.get(key, default)

    def get_int(self, key: str, default: int) -> int:
        value = self._snapshot.get(key)
        return default if value is None else int(value)

    def get_float(self, key: str, default: float) -> float:
        value = self._snapshot.get(key)
        return default if value is None else float(value)

    def get_bool(self, key: str, default: bool) -> bool:
        value = self._snapshot.get(key)
        return default if value is None else bool(value)

    def get_str(self, key: str, default: str) -> str:
        value = self._snapshot.get(key)
        return default if value is None else str(value)


config_cache = ConfigCache()
