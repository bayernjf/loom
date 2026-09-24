"""共享内存 Redis Streams 替身（Q134 原语测试 / Q137 导出 worker 测试复用）。

自包含实现 XADD/XGROUP/XREADGROUP/XACK/XPENDING_RANGE/XCLAIM，无真 Redis。
"""

import time

import redis
from redis.exceptions import ResponseError


class FakeStreamsRedis:
    """实现 XADD/XGROUP/XREADGROUP/XACK/XPENDING_RANGE/XCLAIM 的内存替身。"""

    def __init__(self, *, fail: bool = False):
        self.streams: dict[str, list[tuple[str, dict]]] = {}
        # (stream, group) -> {"pel": {id: {fields, consumer, deliveries, at}},
        #                      "new_index": int}
        self.groups: dict[tuple[str, str], dict] = {}
        self._seq = 0
        self.fail = fail

    def _boom(self):
        if self.fail:
            raise redis.RedisError("boom")

    async def xadd(self, stream, fields, id="*", maxlen=None, approximate=False):
        self._boom()
        self._seq += 1
        entry_id = f"{self._seq}-0"
        self.streams.setdefault(stream, []).append((entry_id, dict(fields)))
        if maxlen is not None:
            buf = self.streams[stream]
            if len(buf) > maxlen:
                self.streams[stream] = buf[-maxlen:]
        return entry_id

    async def xgroup_create(self, stream, group, id="0", mkstream=False):
        self._boom()
        key = (stream, group)
        if key in self.groups:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        if stream not in self.streams:
            if not mkstream:
                raise ResponseError("ERR no such stream")
            self.streams[stream] = []
        self.groups[key] = {"pel": {}, "new_index": 0}
        return True

    async def xreadgroup(self, group, consumer, streams, count=1, block=None):
        self._boom()
        [(stream, marker)] = list(streams.items())
        assert marker == ">", "fake only supports new-message marker '>'"
        g = self.groups[(stream, group)]
        entries = self.streams.get(stream, [])
        start = g["new_index"]
        batch = entries[start : start + count]
        g["new_index"] = start + len(batch)
        now = time.monotonic()
        out = []
        for entry_id, fields in batch:
            g["pel"][entry_id] = {
                "fields": dict(fields),
                "consumer": consumer,
                "deliveries": 1,
                "at": now,
            }
            out.append((entry_id, dict(fields)))
        return [(stream, out)] if out else []

    async def xack(self, stream, group, *ids):
        self._boom()
        pel = self.groups[(stream, group)]["pel"]
        n = 0
        for entry_id in ids:
            if entry_id in pel:
                del pel[entry_id]
                n += 1
        return n

    async def xpending_range(self, stream, group, min, max, count, idle=None):
        self._boom()
        pel = self.groups[(stream, group)]["pel"]
        now = time.monotonic()
        rows = []
        for entry_id, meta in pel.items():
            idle_ms = (now - meta["at"]) * 1000
            if idle is not None and idle_ms < idle:
                continue
            rows.append(
                {
                    "message_id": entry_id,
                    "consumer": meta["consumer"],
                    "time_since_delivered": int(idle_ms),
                    "times_delivered": meta["deliveries"],
                }
            )
        return rows[:count]

    async def xpending(self, stream, group):
        """XPENDING 汇总（Q188 只读深度探针用）：真实未 ACK 条数，不受 count/idle 截断。"""
        self._boom()
        key = (stream, group)
        if key not in self.groups:
            raise ResponseError("NOGROUP No such consumer group")
        pel = self.groups[key]["pel"]
        ids = list(pel)
        return {
            "pending": len(ids),
            "min": ids[0] if ids else None,
            "max": ids[-1] if ids else None,
            "consumers": [
                {"name": name, "pending": sum(1 for m in pel.values() if m["consumer"] == name)}
                for name in {m["consumer"] for m in pel.values()}
            ],
        }

    async def xlen(self, stream):
        self._boom()
        return len(self.streams.get(stream, []))

    async def xclaim(self, stream, group, consumer, min_idle_ms, ids):
        self._boom()
        pel = self.groups[(stream, group)]["pel"]
        now = time.monotonic()
        out = []
        for entry_id in ids:
            meta = pel.get(entry_id)
            if meta is None:
                continue
            if (now - meta["at"]) * 1000 < min_idle_ms:
                continue
            meta["consumer"] = consumer
            meta["deliveries"] += 1
            meta["at"] = now
            out.append((entry_id, dict(meta["fields"])))
        return out
