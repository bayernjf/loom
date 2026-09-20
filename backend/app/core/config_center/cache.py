"""进程内配置快照缓存（14 §2.4 热更新：发布即原子切换）。

V1 为模块化单体单进程：发布后在同事务 after_commit 钩子内原子替换快照，
纯逻辑规则模块可用同步 get_* 读最新值，无需穿 DB。
多副本部署的跨进程广播（Redis Streams/pub-sub）随部署形态落地，挂账见 08 M10。
"""

from collections.abc import Iterable

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

    async def reload_keys(
        self, session: AsyncSession, keys: Iterable[str]
    ) -> None:
        """Q140 单 key 增量失效：只重查给定 key 并原子合并进快照。

        DB 中仍存在的 key 用最新值覆盖；DB 中已删除/不存在的 key 从快照移除
        （配置项被删也要失效，不能残留旧值）。空集合直接返回。相比全量 reload
        显著减少多副本下高频单 key 热更的读放⼤。
        """
        key_list = list(keys)
        if not key_list:
            return
        rows = (
            await session.scalars(
                select(ConfigItem).where(ConfigItem.key.in_(key_list))
            )
        ).all()
        fresh = {row.key: row.value for row in rows}
        snapshot = dict(self._snapshot)
        for key in key_list:
            if key in fresh:
                snapshot[key] = fresh[key]
            else:
                snapshot.pop(key, None)
        self._snapshot = snapshot
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
