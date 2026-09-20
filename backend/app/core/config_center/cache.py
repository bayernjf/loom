"""进程内配置快照缓存（14 §2.4 热更新：发布即原子切换）。

V1 为模块化单体单进程：发布后在同事务 after_commit 钩子内原子替换快照，
纯逻辑规则模块可用同步 get_* 读最新值，无需穿 DB。
多副本部署的跨进程广播（Redis Streams/pub-sub）随部署形态落地，挂账见 08 M10。
"""

import time
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_center.models import ConfigItem


class ConfigCache:
    def __init__(self) -> None:
        self._snapshot: dict[str, object] = {}
        # Q141：每个 key 对应的 ConfigItem.version，增量失效时按版本单调接受，
        # 防止乱序/延迟到达的旧快照把新值回灌（版本号防陈旧）。
        self._versions: dict[str, int] = {}
        # 最近一次成功装载/发布的 monotonic 时间戳，供订阅侧 TTL 兜底判断；
        # invalidate 后回到 None。
        self.loaded_at: float | None = None
        self.loaded = False

    async def reload(self, session: AsyncSession) -> None:
        rows = (await session.scalars(select(ConfigItem))).all()
        # 全量 reload 是一致性兜底来源，以 DB 全表为准整体替换（含版本向量）。
        self._snapshot = {row.key: row.value for row in rows}
        self._versions = {row.key: int(row.version) for row in rows}
        self.loaded = True
        self.loaded_at = time.monotonic()

    async def reload_keys(
        self, session: AsyncSession, keys: Iterable[str]
    ) -> dict[str, int]:
        """Q140 单 key 增量失效：只重查给定 key 并原子合并进快照。

        DB 中仍存在的 key 用最新值覆盖；DB 中已删除/不存在的 key 从快照移除
        （配置项被删也要失效，不能残留旧值）。空集合直接返回。相比全量 reload
        显著减少多副本下高频单 key 热更的读放⼤。

        Q141：值覆盖按 ``ConfigItem.version`` 单调门控——DB 行版本低于本进程已
        持有的版本时视为乱序旧快照，拒绝回灌（计数 skipped）；DB 已删 key 的移除
        是显式失效语义，不受版本门控限制。返回 ``{accepted, skipped, removed}``
        计数，便于调用方观测与测试。
        """
        key_list = list(keys)
        result = {"accepted": 0, "skipped": 0, "removed": 0}
        if not key_list:
            return result
        rows = (
            await session.scalars(
                select(ConfigItem).where(ConfigItem.key.in_(key_list))
            )
        ).all()
        fresh = {row.key: row for row in rows}
        snapshot = dict(self._snapshot)
        versions = dict(self._versions)
        for key in key_list:
            row = fresh.get(key)
            if row is None:
                # 显式失效且 DB 已无此 key：移除值与版本。
                snapshot.pop(key, None)
                if versions.pop(key, None) is not None:
                    result["removed"] += 1
                continue
            current_version = versions.get(key)
            if current_version is not None and int(row.version) < current_version:
                # 乱序旧快照：不回灌新值。
                result["skipped"] += 1
                continue
            snapshot[key] = row.value
            versions[key] = int(row.version)
            result["accepted"] += 1
        self._snapshot = snapshot
        self._versions = versions
        self.loaded = True
        self.loaded_at = time.monotonic()
        return result

    def apply(self, updates: dict[str, object], versions: dict[str, int] | None = None) -> None:
        # 单次 dict 更新 = 读侧原子切换（14 §2.4）。本进程 after_commit 权威发布，
        # 若携带版本（Q141）一并记录版本向量。
        self._snapshot = {**self._snapshot, **updates}
        if versions:
            self._versions = {**self._versions, **versions}
        self.loaded = True
        self.loaded_at = time.monotonic()

    def invalidate(self) -> None:
        self._snapshot = {}
        self._versions = {}
        self.loaded = False
        self.loaded_at = None

    def version_of(self, key: str) -> int | None:
        """Q141：返回 key 当前快照对应的配置版本（未持有为 None）。"""
        return self._versions.get(key)

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
