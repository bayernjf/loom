"""段13 效果回流接收/时序/孤儿分流服务（Q126，05 §1.1.1 / 11 §2.1）。

数据纪律（硬性）：
- metrics 缺席=未采集，键不落库（NULL/省略），绝不当 0、不许估算。
- 幂等：同 content_id + captured_at 幂等覆盖；同 content_id 不同 captured_at 追加时序。
- 孤儿：推送的 content_id 对不上本系统有效成品（含已 discarded）进 orphan 队列。
- 整批 all-or-nothing：任一记录非法即 422，不写部分数据（同 Q93 口径）。

本切片不含：Q60a 孤儿人工认领动作、customer-backfill 客户端点、效果反哺/评分
校准算法（口径原文未给，标【待补】），均随段13 后续片/V2。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import CONTENT_DISCARDED, ContentProduct
from app.core.api_keys.models import AgentApiKey
from app.core.api_keys.service import PLATFORM_TENANT
from app.core.audit import append_audit
from app.core.effects.models import (
    METRIC_COUNTERS,
    METRIC_KEYS,
    METRIC_RATE_KEYS,
    STATUS_MATCHED,
    STATUS_ORPHAN,
    EffectRecord,
)
from app.core.effects.schemas import EffectBatchIn, EffectRecordIn


class EffectValidationError(Exception):
    """整批中第 index 条（0 基）记录的字段非法；调用方回 422。"""

    def __init__(self, index: int, field: str, message: str) -> None:
        self.index = index
        self.field = field
        super().__init__(message)


def _is_real_number(value: object) -> bool:
    """计数/比率须为数值；bool 是 int 子类，显式排除。"""

    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize_metrics(index: int, raw: object) -> dict | None:
    """校验并稀疏化 metrics：缺席/None 不落，未知键与非法类型 422。

    计数六键须为非负整数；read_rate 须为 0..1 数值；其余未知键一律拒绝。
    """

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise EffectValidationError(index, "metrics", "metrics must be an object")

    normalized: dict[str, object] = {}
    for key, value in raw.items():
        if key not in METRIC_KEYS:
            raise EffectValidationError(index, f"metrics.{key}", "unknown metric key")
        if value is None:
            # 显式 null 等同未采集，省略该键（绝不写 0）。
            continue
        if key in METRIC_COUNTERS and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise EffectValidationError(
                index, f"metrics.{key}", "counter must be a non-negative integer"
            )
        # METRIC_COUNTERS 与 METRIC_RATE_KEYS 互斥，两个独立 if 等价于互斥分支。
        if key in METRIC_RATE_KEYS and (
            not _is_real_number(value) or not 0 <= float(value) <= 1
        ):
            raise EffectValidationError(
                index, f"metrics.{key}", "rate must be a number in [0, 1]"
            )
        normalized[key] = value
    return normalized or None


def _as_utc(dt: datetime) -> datetime:
    """aware datetime 归一到 UTC；sqlite 读回的 naive 值视为 UTC。"""

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def validate_record(
    index: int, rec: EffectRecordIn
) -> tuple[str, str, datetime, dict | None]:
    """校验单条记录（不碰库），返回归一四元组；captured_at 须带时区。"""

    content_id = rec.content_id.strip()
    if not content_id:
        raise EffectValidationError(index, "content_id", "content_id is required")
    platform_post_id = rec.platform_post_id.strip()
    if not platform_post_id:
        raise EffectValidationError(
            index, "platform_post_id", "platform_post_id is required"
        )
    if rec.captured_at.tzinfo is None:
        raise EffectValidationError(
            index, "captured_at", "captured_at must include a timezone"
        )
    captured_at = _as_utc(rec.captured_at)
    metrics = normalize_metrics(index, rec.metrics)
    return content_id, platform_post_id, captured_at, metrics


async def ingest_effects(
    session: AsyncSession,
    *,
    batch: EffectBatchIn,
    key: AgentApiKey,
) -> dict[str, int]:
    """整批接收效果记录（all-or-nothing），返回 {received,matched,orphan,upserted}。"""

    source = batch.source.strip()
    if not source:
        # pydantic min_length=1 已挡空串，这里防纯空白。
        raise EffectValidationError(-1, "source", "source is required")

    # 1) 逐条校验/归一 + 批内幂等键去重（不写库）。
    normalized: list[tuple[str, str, datetime, dict | None]] = []
    seen: set[tuple[str, datetime]] = set()
    for index, rec in enumerate(batch.records):
        content_id, post_id, captured_at, metrics = validate_record(index, rec)
        dedup_key = (content_id, captured_at)
        if dedup_key in seen:
            raise EffectValidationError(
                index, "captured_at", "duplicate content_id + captured_at within batch"
            )
        seen.add(dedup_key)
        normalized.append((content_id, post_id, captured_at, metrics))

    external_ids = {item[0] for item in normalized}

    # 2) 一次性解析本系统有效成品（discarded 不作为命中目标，按孤儿处理）。
    content_rows = (
        await session.scalars(
            select(ContentProduct).where(ContentProduct.content_id.in_(external_ids))
        )
    ).all()
    content_map = {
        row.content_id: row
        for row in content_rows
        if row.status != CONTENT_DISCARDED
    }

    # 3) 一次性取这批涉及的既有记录，按幂等键建索引（captured_at 统一 UTC 比较）。
    existing_rows = (
        await session.scalars(
            select(EffectRecord).where(
                EffectRecord.external_content_id.in_(external_ids)
            )
        )
    ).all()
    existing_map = {
        (row.external_content_id, _as_utc(row.captured_at)): row for row in existing_rows
    }

    matched = orphan = upserted = 0
    now = datetime.now(UTC)
    for content_id, post_id, captured_at, metrics in normalized:
        content = content_map.get(content_id)
        row = existing_map.get((content_id, captured_at))
        if row is not None:
            # 幂等覆盖（Q60）：刷新来源/帖子/指标，重算匹配，不新增行。
            row.source = source
            row.platform_post_id = post_id
            row.metrics = metrics
            if content is not None:
                row.matched_content_id = content.content_id
                row.tenant_id = content.tenant_id
                row.status = STATUS_MATCHED
            else:
                row.matched_content_id = None
                row.tenant_id = None
                row.status = STATUS_ORPHAN
            row.received_by = key.key_id
            row.updated_at = now
            upserted += 1
        else:
            if content is not None:
                matched_content_id = content.content_id
                tenant_id = content.tenant_id
                status = STATUS_MATCHED
            else:
                matched_content_id = None
                tenant_id = None
                status = STATUS_ORPHAN
            session.add(
                EffectRecord(
                    source=source,
                    external_content_id=content_id,
                    matched_content_id=matched_content_id,
                    tenant_id=tenant_id,
                    platform_post_id=post_id,
                    captured_at=captured_at,
                    metrics=metrics,
                    status=status,
                    received_by=key.key_id,
                )
            )
        if content is not None:
            matched += 1
        else:
            orphan += 1

    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=key.key_id,
        actor_roles=[],
        action="effect.batch_received",
        entity_type="effect_batch",
        entity_id=str(uuid.uuid4()),
        detail={
            "source": source,
            "received": len(normalized),
            "matched": matched,
            "orphan": orphan,
            "upserted": upserted,
        },
    )

    return {
        "received": len(normalized),
        "matched": matched,
        "orphan": orphan,
        "upserted": upserted,
    }


async def list_orphans(
    session: AsyncSession, *, limit: int, offset: int
) -> list[EffectRecord]:
    """孤儿队列：跨租户 status=orphan，按采集时间先到先列。"""

    rows = await session.scalars(
        select(EffectRecord)
        .where(EffectRecord.status == STATUS_ORPHAN)
        .order_by(EffectRecord.captured_at.asc(), EffectRecord.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows.all())


async def list_series(
    session: AsyncSession, content_id: str, *, limit: int, offset: int
) -> list[EffectRecord]:
    """某成品的效果时间序列（matched_content_id），captured_at 升序。"""

    rows = await session.scalars(
        select(EffectRecord)
        .where(EffectRecord.matched_content_id == content_id)
        .order_by(EffectRecord.captured_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows.all())


def effect_view(row: EffectRecord) -> dict:
    return {
        "record_id": row.record_id,
        "source": row.source,
        "content_id": row.external_content_id,
        "matched_content_id": row.matched_content_id,
        "tenant_id": row.tenant_id,
        "platform_post_id": row.platform_post_id,
        "captured_at": row.captured_at,
        "metrics": row.metrics,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
